"""
Main application window for Ghost AI.
Frameless, translucent, always-on-top window supporting:
- Unified top header with Ghost AI branding, Home icon, closable conversation tabs,
  new tab button, ghost mode toggle, settings, and window controls
- History View: 'Your conversations' with category-aware cards and date grouping
- Chat View: 'Your conversation workspace' with modern integrated prompt card
- Multi-chat conversation histories saved locally
- True Win32 / macOS Ghost Mode click-through and screen capture invisibility
Strictly preserves the standard ArrowCursor across all elements.
"""

import sys
import time
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, Signal, QObject, QEvent
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QPainter,
    QColor,
    QPen,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QStackedWidget,
    QMessageBox,
)

from .controls import ControlsWindow
from .platform_utils import (
    set_click_through,
    exclude_from_taskbar,
    set_capture_excluded,
    is_capture_excluded,
)
from .persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    create_chat_dict,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
)
from .chat_view import ChatView
from .history_view import HistoryView
from .settings_dialog import SettingsDialog
from .header_bar import HeaderBar


class NoToolTipFilter(QObject):
    """Global event filter that suppresses all QToolTip events for stealth Ghost Mode."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().eventFilter(watched, event)


class ResizeGrip(QWidget):
    """Bottom-right resize grip maintaining standard ArrowCursor."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(160, 160, 160, 120), 1.5))
        painter.drawLine(10, 4, 10, 4)
        painter.drawLine(6, 8, 10, 8)
        painter.drawLine(2, 12, 10, 12)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)


class MainWindow(QWidget):
    """
    Frameless, floating, always-on-top AI chat window.
    Features:
    - Unified header with tabs and window controls
    - Multi-chat conversation histories saved locally
    - Home Page: responsive date-grouped list of saved conversations
    - Chat Room: streaming responses from OpenAI / Anthropic / Groq / Ollama / DeepSeek
    - True Win32 / macOS Ghost Mode click-through and screen capture invisibility
    """

    def __init__(self):
        super().__init__()

        self._ghost_mode = False
        self._is_dragging = False
        self._is_resizing = False
        self._drag_start_pos = QPoint()
        self._resize_start_pos = QPoint()
        self._resize_start_geom = QRect()

        # State
        self._chats: List[Dict[str, Any]] = []
        self._open_tabs: List[str] = []
        self._active_chat_id: Optional[str] = None
        self._view_mode: str = "list"
        self._is_shutting_down: bool = False
        self._shutdown_timer: Optional[QTimer] = None
        self._shutdown_deadline: float = 0.0

        # Window Flags: Frameless, Tool, Always On Top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Autosave debounce timer (500ms)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_state)

        # Build UI layout
        self._init_ui()

        # Keyboard shortcuts
        self._setup_shortcuts()

        # Independent controls window (Blue & Red micro-dots)
        self.controls = ControlsWindow()
        self.controls.toggle_ghost_requested.connect(self.toggle_ghost_mode)
        self.controls.close_requested.connect(self.close_application)

        # Global stealth tooltip suppression
        app_inst = QGuiApplication.instance()
        if app_inst:
            self._tooltip_filter = NoToolTipFilter(self)
            app_inst.installEventFilter(self._tooltip_filter)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Header Bar
        self.header_bar = HeaderBar(self)
        self.header_bar.home_clicked.connect(self.show_home)
        self.header_bar.new_chat_clicked.connect(self.create_new_chat)
        self.header_bar.tab_selected.connect(self.open_chat)
        self.header_bar.tab_closed.connect(self.close_tab)
        self.header_bar.settings_clicked.connect(self.open_settings)
        main_layout.addWidget(self.header_bar)

        # 2. Stacked Widget: 0 = HistoryView (Home), 1 = ChatView
        self.stack = QStackedWidget(self)
        self.stack.setCursor(Qt.CursorShape.ArrowCursor)

        self.history_view = HistoryView(self)
        self.history_view.chat_selected.connect(self.open_chat)
        self.history_view.new_chat_requested.connect(self.create_new_chat)
        self.history_view.delete_chat_requested.connect(self.delete_chat)
        self.history_view.settings_requested.connect(self.open_settings)
        self.history_view.view_mode_changed.connect(self._on_view_mode_changed)
        self.history_view.chat_renamed.connect(self._on_chat_renamed)
        self.stack.addWidget(self.history_view)

        self.chat_view = ChatView(self)
        self.chat_view.home_requested.connect(self.show_home)
        self.chat_view.new_chat_requested.connect(self.create_new_chat)
        self.chat_view.settings_requested.connect(self.open_settings)
        self.chat_view.chat_updated.connect(self._on_active_chat_updated)
        self.stack.addWidget(self.chat_view)

        main_layout.addWidget(self.stack, 1)

        # Bottom-right Resize Grip
        self.resize_grip = ResizeGrip(self)
        self.resize_grip.setParent(self)
        self.resize_grip.show()

    def _setup_shortcuts(self) -> None:
        """Register keyboard shortcuts."""
        # Toggle Ghost Mode: Ctrl+G
        sc_ghost = QShortcut(QKeySequence("Ctrl+G"), self)
        sc_ghost.activated.connect(self.toggle_ghost_mode)

        # New Chat: Ctrl+N
        sc_new = QShortcut(QKeySequence("Ctrl+N"), self)
        sc_new.activated.connect(self.create_new_chat)

        # Home / History: Ctrl+H
        sc_home = QShortcut(QKeySequence("Ctrl+H"), self)
        sc_home.activated.connect(self.show_home)

        # Settings: Ctrl+,
        sc_settings = QShortcut(QKeySequence("Ctrl+,"), self)
        sc_settings.activated.connect(self.open_settings)

        # Close App: Ctrl+Q
        sc_close = QShortcut(QKeySequence("Ctrl+Q"), self)
        sc_close.activated.connect(self.close_application)

        # Search focus: Ctrl+K
        sc_search = QShortcut(QKeySequence("Ctrl+K"), self)
        sc_search.activated.connect(self._focus_search)

    def _focus_search(self) -> None:
        self.show_home()
        self.history_view.search_edit.setFocus()
        self.history_view.search_edit.selectAll()

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def paintEvent(self, event) -> None:
        """Render stealth dark translucent background matching modern obsidian aesthetic."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._ghost_mode:
            bg_color = QColor(14, 14, 19, 140)
            border_color = QColor(139, 92, 246, 60)
        else:
            bg_color = QColor(14, 14, 19, 245)
            border_color = QColor(255, 255, 255, 22)

        painter.setBrush(bg_color)
        painter.setPen(border_color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    def show_app(self) -> None:
        """Show the application and initialize native window properties."""
        data = load_data()
        self._chats = data.get("chats", [])
        self._view_mode = data.get("view_mode", "list")
        saved_view = data.get("current_view", "home")
        saved_active_id = data.get("active_chat_id")
        self._open_tabs = data.get("open_tabs", [])

        # Sanitize and apply geometry
        geom = data.get("geometry", {})
        x, y, w, h = sanitize_geometry(
            geom.get("x"), geom.get("y"), geom.get("width"), geom.get("height")
        )
        self.setGeometry(x, y, w, h)

        # Ensure tabs contain active chat or initial recent chats
        if not self._open_tabs and self._chats:
            self._open_tabs = [c["id"] for c in self._chats[:3]]

        self.history_view.set_chats(self._chats, self._view_mode)
        self._sync_tabs()

        # Restore view
        if saved_view == "chat" and saved_active_id and any(c.get("id") == saved_active_id for c in self._chats):
            self.open_chat(saved_active_id)
        else:
            self.show_home()

        self.show()

        # Apply native platform attributes (taskbar exclusion and capture protection)
        hwnd = int(self.winId())
        exclude_from_taskbar(hwnd)
        capture_ok = set_capture_excluded(hwnd, True)
        if not capture_ok or not is_capture_excluded(hwnd):
            logger.warning("Screen capture protection could not be verified for main window")

        # Initialize and position floating controls
        self.controls.show_controls(self.geometry())

        # If ghost mode was enabled in saved state, activate it
        if data.get("ghost_mode", False):
            self.toggle_ghost_mode()

    def _sync_tabs(self) -> None:
        """Keep header tabs synchronized with _open_tabs."""
        chat_lookup = {c["id"]: c for c in self._chats}
        open_chats = [chat_lookup[cid] for cid in self._open_tabs if cid in chat_lookup]
        self.header_bar.set_open_tabs(open_chats, self._active_chat_id)

    def show_home(self) -> None:
        """Switch to History overview page."""
        self.history_view.set_chats(self._chats, self._view_mode)
        self.stack.setCurrentIndex(0)
        self.header_bar.set_home_active(True)
        self._sync_tabs()
        self._schedule_save()

    def open_chat(self, chat_id: str) -> None:
        """Switch to Chat room page with selected conversation."""
        chat = next((c for c in self._chats if c.get("id") == chat_id), None)
        if not chat:
            return

        if chat_id not in self._open_tabs:
            self._open_tabs.append(chat_id)

        self._active_chat_id = chat_id
        self.chat_view.set_active_chat(chat)
        self.stack.setCurrentIndex(1)
        self.header_bar.set_home_active(False)
        self._sync_tabs()
        self._schedule_save()

    def create_new_chat(self) -> None:
        """Create a new chat conversation and open it."""
        new_chat = create_chat_dict("New Chat")
        self._chats.insert(0, new_chat)
        if new_chat["id"] not in self._open_tabs:
            self._open_tabs.insert(0, new_chat["id"])
        self.open_chat(new_chat["id"])

    def close_tab(self, chat_id: str) -> None:
        """Close a conversation tab from the header."""
        if chat_id in self._open_tabs:
            self._open_tabs.remove(chat_id)

        if self._active_chat_id == chat_id:
            if self._open_tabs:
                self.open_chat(self._open_tabs[-1])
            else:
                self.show_home()
        else:
            self._sync_tabs()

        self._schedule_save()

    def delete_chat(self, chat_id: str) -> None:
        """Delete a chat conversation and cancel any running generation."""
        self.chat_view.cancel_generations_for_chat(chat_id)

        if chat_id in self._open_tabs:
            self._open_tabs.remove(chat_id)

        self._chats = [c for c in self._chats if c.get("id") != chat_id]
        if self._active_chat_id == chat_id:
            if self._open_tabs:
                self.open_chat(self._open_tabs[-1])
            else:
                self.show_home()

        self.history_view.set_chats(self._chats, self._view_mode)
        self._sync_tabs()
        self._schedule_save()

    def _on_chat_renamed(self, chat_id: str, new_title: str) -> None:
        for c in self._chats:
            if c.get("id") == chat_id:
                c["title"] = new_title
                break
        self.header_bar.update_tab_title(chat_id, new_title)
        if self._active_chat_id == chat_id:
            self.chat_view.title_edit.setText(new_title)
        self.history_view.set_chats(self._chats, self._view_mode)
        self._schedule_save()

    def _on_active_chat_updated(self) -> None:
        if self._active_chat_id:
            chat = next((c for c in self._chats if c.get("id") == self._active_chat_id), None)
            if chat:
                self.header_bar.update_tab_title(self._active_chat_id, chat.get("title", ""))
        self._schedule_save()

    def open_settings(self) -> None:
        """Display the Settings dialog."""
        dialog = SettingsDialog(self)
        dialog.settings_saved.connect(self._on_settings_saved)
        dx = self.x() + (self.width() - dialog.width()) // 2
        dy = self.y() + (self.height() - dialog.sizeHint().height()) // 2
        dialog.move(dx, dy)
        dialog.exec()

    def _on_settings_saved(self, config: Dict[str, Any]) -> None:
        """Update active views when settings change."""
        self.chat_view.check_api_key_banner()

    def _on_view_mode_changed(self, mode: str) -> None:
        self._view_mode = mode
        self._schedule_save()

    def toggle_ghost_mode(self) -> None:
        """Toggle true click-through Ghost Mode."""
        self.set_ghost_mode(not self._ghost_mode)

    def set_ghost_mode(self, enabled: bool) -> None:
        """Set true click-through Ghost Mode on or off after verifying platform success."""
        hwnd = int(self.winId())
        ok = set_click_through(hwnd, enabled)
        if not ok and sys.platform == "win32":
            logger.warning("Failed to toggle native click-through on HWND %s", hwnd)
            return

        self._ghost_mode = enabled
        self.controls.set_ghost_active(enabled)
        self.header_bar.set_ghost_mode_active(enabled)
        if enabled:
            self.setWindowOpacity(0.35)
        else:
            self.setWindowOpacity(1.0)
        self.update()
        self._schedule_save()

    def closeEvent(self, event) -> None:
        """Handle window close event with non-blocking graceful shutdown."""
        if self._is_shutting_down:
            if self.chat_view.has_active_workers():
                event.ignore()
                return
            event.accept()
            return

        if self.chat_view.has_active_workers():
            event.ignore()
            self.close_application()
            return

        self._finish_close()
        event.accept()

    def close_application(self) -> None:
        """Safely persist state and terminate the application via asynchronous graceful shutdown."""
        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        self._save_timer.stop()

        if not self.chat_view.has_active_workers():
            self._finish_close()
            return

        # Request cooperative cancellation across all AI and voice threads
        self.chat_view.cancel_all_workers()

        # Non-blocking async poll loop
        self._shutdown_deadline = time.time() + 5.0
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(50)
        self._shutdown_timer.timeout.connect(self._check_shutdown_complete)
        self._shutdown_timer.start()

    def _check_shutdown_complete(self) -> None:
        """Poll worker status until all threads stop or deadline expires."""
        if not self.chat_view.has_active_workers() or time.time() >= self._shutdown_deadline:
            if self._shutdown_timer:
                self._shutdown_timer.stop()
                self._shutdown_timer = None
            self._finish_close()

    def _finish_close(self) -> None:
        """Finalize application termination."""
        self._save_state()
        if hasattr(self, "controls"):
            self.controls.close()
        self.close()
        app = QGuiApplication.instance()
        if app and "pytest" not in sys.modules:
            app.quit()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_state(self) -> None:
        """Serialize chat conversations and geometry."""
        geom = self.geometry()
        current_view_str = "chat" if self.stack.currentIndex() == 1 else "home"
        payload = {
            "chats": self._chats,
            "open_tabs": self._open_tabs,
            "active_chat_id": self._active_chat_id,
            "view_mode": self._view_mode,
            "current_view": current_view_str,
            "geometry": {
                "x": geom.x(),
                "y": geom.y(),
                "width": geom.width(),
                "height": geom.height(),
            },
            "ghost_mode": self._ghost_mode,
        }
        save_data(payload)

    # Mouse & Window Drag / Resize Handling
    def mousePressEvent(self, event) -> None:
        if self._ghost_mode:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            grip_rect = QRect(self.width() - 20, self.height() - 20, 20, 20)
            if grip_rect.contains(event.position().toPoint()):
                self._is_resizing = True
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return

            # Check if clicked in top drag area (top 46px)
            if event.position().y() <= 46:
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            new_w = max(360, self._resize_start_geom.width() + delta.x())
            new_h = max(420, self._resize_start_geom.height() + delta.y())
            self.resize(new_w, new_h)
            event.accept()
            return

        if self._is_dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(new_pos)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging or self._is_resizing:
                self._is_dragging = False
                self._is_resizing = False
                self._schedule_save()
        super().mouseReleaseEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "controls"):
            self.controls.sync_position(self.geometry())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "controls"):
            self.controls.sync_position(self.geometry())
        if hasattr(self, "resize_grip"):
            self.resize_grip.move(self.width() - 14, self.height() - 14)
