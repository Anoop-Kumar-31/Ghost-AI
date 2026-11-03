"""
Unified Header and Tab Bar for Ghost AI.
Matches the modern dark stealth UI design with branding, home icon,
closable conversation tabs, new tab button, and settings.
Strictly preserves the standard ArrowCursor across all elements.
Window controls (red/blue dots) are managed by the independent ControlsWindow.
"""

from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
    QScrollArea,
)

from .icon_manager import get_icon, get_pixmap, IconButton, COLOR_DEFAULT, COLOR_ACTIVE


class ChatTab(QFrame):
    """
    A single conversation tab in the top header.
    Shows the chat title and a close button '×'.
    """

    tab_clicked = Signal(str)
    tab_closed = Signal(str)

    def __init__(
        self,
        chat_id: str,
        title: str,
        is_active: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.chat_id = chat_id
        self._is_active = is_active
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._init_ui(title)
        self._apply_style()

    def _init_ui(self, title: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 6, 3)
        layout.setSpacing(6)

        # Truncate title if too long
        display_title = title.strip() or "Untitled Chat"
        if len(display_title) > 20:
            display_title = display_title[:18] + "…"

        self.title_lbl = QLabel(display_title, self)
        self.title_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(self.title_lbl)

        # Close button '×'
        self.close_btn = QPushButton(self)
        self.close_btn.setFixedSize(16, 16)
        self.close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setIcon(get_icon("x", 10, COLOR_DEFAULT))
        self.close_btn.setIconSize(QSize(10, 10))
        self.close_btn.clicked.connect(self._on_close_clicked)
        layout.addWidget(self.close_btn)

    def _apply_style(self) -> None:
        if self._is_active:
            self.close_btn.setIcon(get_icon("x", 10, "#a1a1aa"))
            self.setStyleSheet(
                """
                ChatTab {
                    background-color: #201b33;
                    border: 1px solid rgba(139, 92, 246, 0.45);
                    border-radius: 8px;
                }
                QLabel {
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                }
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: rgba(239, 68, 68, 0.2);
                }
                """
            )
        else:
            self.close_btn.setIcon(get_icon("x", 10, "#71717a"))
            self.setStyleSheet(
                """
                ChatTab {
                    background-color: #14131d;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: 8px;
                }
                ChatTab:hover {
                    background-color: #1a1827;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                }
                QLabel {
                    color: #9ca3af;
                    font-size: 11px;
                    background: transparent;
                }
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: rgba(239, 68, 68, 0.2);
                }
                """
            )

    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._apply_style()

    def set_title(self, title: str) -> None:
        display_title = title.strip() or "Untitled Chat"
        if len(display_title) > 20:
            display_title = display_title[:18] + "…"
        self.title_lbl.setText(display_title)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.tab_clicked.emit(self.chat_id)
        super().mousePressEvent(event)

    def _on_close_clicked(self) -> None:
        self.tab_closed.emit(self.chat_id)


class HeaderBar(QWidget):
    """
    Unified Top Header Bar for Ghost AI.
    Contains:
    - Logo pill 'Ghost AI'
    - Home button (conversations icon)
    - Dynamic Tab Bar for conversations
    - New Chat button '+'
    - Settings button
    Window controls (red/blue dots) live in the separate ControlsWindow.
    """

    home_clicked = Signal()
    new_chat_clicked = Signal()
    tab_selected = Signal(str)
    tab_closed = Signal(str)
    settings_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._tabs: Dict[str, ChatTab] = {}
        self._active_chat_id: Optional[str] = None
        self._is_home_active: bool = True

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # 1. Branding: Ghost AI Logo pill (no border, clean look)
        brand_frame = QFrame(self)
        brand_frame.setCursor(Qt.CursorShape.ArrowCursor)
        brand_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1e1730;
                border: none;
                border-radius: 8px;
                padding: 2px 4px;
            }
            """
        )
        brand_layout = QHBoxLayout(brand_frame)
        brand_layout.setContentsMargins(1,1,1,1)
        brand_layout.setSpacing(0)

        ghost_icon_lbl = QLabel(brand_frame)
        ghost_icon_lbl.setPixmap(get_pixmap("ghost", 15, COLOR_ACTIVE))
        ghost_icon_lbl.setStyleSheet("background: transparent;")
        brand_layout.addWidget(ghost_icon_lbl)

        brand_text_lbl = QLabel("Ghost AI", brand_frame)
        brand_text_lbl.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: 700; background: transparent;"
        )
        brand_layout.addWidget(brand_text_lbl)
        layout.addWidget(brand_frame)

        # 2. Home Button (house icon — no border)
        self.home_btn = IconButton(
            "house",
            size=16,
            btn_size=30,
            parent=self,
        )
        self.home_clicked_signal = self.home_clicked
        self.home_btn.clicked.connect(self.home_clicked.emit)
        layout.addWidget(self.home_btn)

        # 3. Horizontal Tabs Container
        self.tabs_container = QWidget(self)
        self.tabs_container.setCursor(Qt.CursorShape.ArrowCursor)
        self.tabs_layout = QHBoxLayout(self.tabs_container)
        self.tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_layout.setSpacing(6)
        layout.addWidget(self.tabs_container)

        # 4. New Tab '+' button
        self.new_tab_btn = IconButton(
            "plus",
            size=14,
            btn_size=26,
            parent=self,
        )
        self.new_tab_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.2);
            }
            """
        )
        self.new_tab_btn.clicked.connect(self.new_chat_clicked.emit)
        layout.addWidget(self.new_tab_btn)

        layout.addStretch(1)

        # 5. Settings gear button — improved icon, no border
        self.settings_btn = IconButton(
            "settings",
            size=16,
            btn_size=30,
            parent=self,
        )
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        layout.addWidget(self.settings_btn)

        # Right spacing to leave room for the floating ControlsWindow red/blue dots
        layout.addSpacing(48)

        self._update_home_btn_style()

    def _update_home_btn_style(self) -> None:
        self.home_btn.set_active_color(self._is_home_active)
        if self._is_home_active:
            self.home_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #271a47;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #31215a;
                }
                """
            )
        else:
            self.home_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                }
                """
            )

    def set_ghost_mode_active(self, active: bool) -> None:
        """No-op: ghost mode visual state is now handled by ControlsWindow only."""
        pass

    def set_home_active(self, active: bool) -> None:
        self._is_home_active = active
        self._update_home_btn_style()
        if active:
            for tab in self._tabs.values():
                tab.set_active(False)

    def set_open_tabs(self, chats: List[Dict[str, Any]], active_chat_id: Optional[str]) -> None:
        """Synchronize tabs with the open conversations list."""
        self._active_chat_id = active_chat_id
        chat_dict = {str(c.get("id")): c for c in chats}

        # Remove closed tabs
        current_ids = list(self._tabs.keys())
        for cid in current_ids:
            if cid not in chat_dict:
                tab = self._tabs.pop(cid)
                tab.deleteLater()

        # Add or update tabs
        for chat in chats:
            cid = str(chat.get("id"))
            title = str(chat.get("title") or "Untitled Chat")
            is_active = (not self._is_home_active) and (cid == active_chat_id)

            if cid in self._tabs:
                tab = self._tabs[cid]
                tab.set_title(title)
                tab.set_active(is_active)
            else:
                tab = ChatTab(cid, title, is_active=is_active, parent=self.tabs_container)
                tab.tab_clicked.connect(self.tab_selected.emit)
                tab.tab_closed.connect(self.tab_closed.emit)
                self.tabs_layout.addWidget(tab)
                self._tabs[cid] = tab

    def update_tab_title(self, chat_id: str, new_title: str) -> None:
        if chat_id in self._tabs:
            self._tabs[chat_id].set_title(new_title)

