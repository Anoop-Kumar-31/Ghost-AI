"""
History and Home view for Ghost AI.
Displays saved chat sessions in a responsive Grid or List layout.
Supports search filtering, deleting chats, switching view modes,
and starting new chats.
Strictly preserves the standard ArrowCursor across all elements.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QScrollArea,
)

from .chat_view import NoIBeamLineEdit


def format_relative_time(iso_str: str) -> str:
    """Format an ISO timestamp into a human-readable relative string."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now()
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "Just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


class ChatCard(QFrame):
    """
    Clickable chat card component for Grid and List views.
    Displays chat title, snippet preview, message count, and delete button.
    Strictly preserves Qt.CursorShape.ArrowCursor.
    """

    clicked = Signal(str)
    delete_requested = Signal(str)

    def __init__(
        self,
        chat: Dict[str, Any],
        is_list_view: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.chat_id = str(chat.get("id", ""))
        self.is_list_view = is_list_view
        self.setCursor(Qt.CursorShape.ArrowCursor)

        title = str(chat.get("title") or "Untitled Chat")
        messages = chat.get("messages", [])
        msg_count = len(messages)
        date_str = format_relative_time(str(chat.get("updated_at", "")))

        # Find latest message for snippet
        snippet = "No messages yet"
        if messages:
            last_msg = messages[-1]
            last_content = str(last_msg.get("content", "")).strip()
            if last_content:
                snippet = last_content.replace("\n", " ")
                if len(snippet) > 65:
                    snippet = snippet[:62] + "..."

        self.setObjectName("ChatCard")
        self.setStyleSheet(
            """
            QFrame#ChatCard {
                background-color: rgba(39, 39, 42, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QFrame#ChatCard:hover {
                background-color: rgba(59, 130, 246, 0.15);
                border: 1px solid rgba(59, 130, 246, 0.4);
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Top row: Title + Message Count + Delete button
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.title_lbl.setStyleSheet(
            "color: #f4f4f5; font-size: 11px; font-weight: 700; background: transparent;"
        )
        top_row.addWidget(self.title_lbl)
        top_row.addStretch()

        if msg_count > 0:
            count_lbl = QLabel(f"{msg_count} msgs", self)
            count_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            count_lbl.setStyleSheet(
                "color: #71717a; font-size: 9px; background: rgba(255,255,255,0.06); "
                "border-radius: 3px; padding: 1px 4px;"
            )
            top_row.addWidget(count_lbl)

        self.del_btn = QPushButton("×", self)
        self.del_btn.setFixedSize(16, 16)
        self.del_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.del_btn.setStyleSheet(
            """
            QPushButton {
                color: #71717a;
                background: transparent;
                border: none;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
            """
        )
        self.del_btn.clicked.connect(self._on_delete_clicked)
        top_row.addWidget(self.del_btn)
        layout.addLayout(top_row)

        # Snippet preview
        self.snippet_lbl = QLabel(snippet, self)
        self.snippet_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.snippet_lbl.setWordWrap(True)
        self.snippet_lbl.setStyleSheet("color: #a1a1aa; font-size: 10px; background: transparent;")
        layout.addWidget(self.snippet_lbl)

        # Footer row: Relative time
        if date_str:
            self.date_lbl = QLabel(date_str, self)
            self.date_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.date_lbl.setStyleSheet("color: #71717a; font-size: 9px; background: transparent;")
            layout.addWidget(self.date_lbl)

        if not is_list_view:
            self.setMinimumHeight(84)
            self.setMaximumHeight(115)
        else:
            self.setMinimumHeight(48)
            self.setMaximumHeight(70)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.chat_id)
        super().mousePressEvent(event)

    def _on_delete_clicked(self) -> None:
        self.delete_requested.emit(self.chat_id)


class HistoryView(QWidget):
    """
    Home page displaying the grid or list of past chat sessions.
    Supports real-time search, responsive grid recalculation, and view toggling.
    """

    chat_selected = Signal(str)
    new_chat_requested = Signal()
    delete_chat_requested = Signal(str)
    settings_requested = Signal()
    view_mode_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._chats: List[Dict[str, Any]] = []
        self._view_mode: str = "grid"  # "grid" or "list"
        self._current_cols: int = -1
        self._search_query: str = ""

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Top Bar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        title_lbl = QLabel("👻 Ghost AI", self)
        title_lbl.setStyleSheet("color: #f4f4f5; font-size: 12px; font-weight: 700;")
        top_bar.addWidget(title_lbl)

        top_bar.addStretch()

        # View mode toggle (Grid / List)
        self.toggle_view_btn = QPushButton("⊞", self)
        self.toggle_view_btn.setFixedSize(24, 24)
        self.toggle_view_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.toggle_view_btn.setToolTip("Toggle Grid / List View")
        self.toggle_view_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(39, 39, 42, 0.8);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: rgba(63, 63, 70, 0.8);
            }
            """
        )
        self.toggle_view_btn.clicked.connect(self._toggle_view_mode)
        top_bar.addWidget(self.toggle_view_btn)

        # Settings gear button
        settings_btn = QPushButton("⚙", self)
        settings_btn.setFixedSize(24, 24)
        settings_btn.setCursor(Qt.CursorShape.ArrowCursor)
        settings_btn.setToolTip("Settings & API Key")
        settings_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(39, 39, 42, 0.8);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: rgba(63, 63, 70, 0.8);
            }
            """
        )
        settings_btn.clicked.connect(self.settings_requested.emit)
        top_bar.addWidget(settings_btn)

        # New Chat button
        new_btn = QPushButton("+ New Chat", self)
        new_btn.setFixedSize(86, 24)
        new_btn.setCursor(Qt.CursorShape.ArrowCursor)
        new_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        new_btn.clicked.connect(self.new_chat_requested.emit)
        top_bar.addWidget(new_btn)

        # Spacing reserved for Blue and Red controls window
        top_bar.addSpacing(42)
        main_layout.addLayout(top_bar)

        # Search Bar
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        self.search_edit = NoIBeamLineEdit(self)
        self.search_edit.setPlaceholderText("🔍 Search conversations...")
        self.search_edit.setStyleSheet(
            """
            QLineEdit {
                background-color: rgba(39, 39, 42, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                color: #f4f4f5;
                font-size: 11px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
                background-color: rgba(39, 39, 42, 0.9);
            }
            """
        )
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_edit)
        main_layout.addLayout(search_row)

        # Scroll Area for Chat Cards
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setCursor(Qt.CursorShape.ArrowCursor)
        self.scroll_area.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.scroll_area.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.1);
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.25);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            """
        )

        self.cards_container = QWidget()
        self.cards_container.setCursor(Qt.CursorShape.ArrowCursor)
        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, 1)

    def set_chats(self, chats: List[Dict[str, Any]], view_mode: str = "grid") -> None:
        """Update chats list and view mode."""
        self._chats = chats
        self._view_mode = view_mode
        self.toggle_view_btn.setText("☰" if self._view_mode == "grid" else "⊞")
        self._rebuild_cards()

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self.toggle_view_btn.setText("☰" if self._view_mode == "grid" else "⊞")
        self._rebuild_cards()

    def _toggle_view_mode(self) -> None:
        self._view_mode = "list" if self._view_mode == "grid" else "grid"
        self.toggle_view_btn.setText("☰" if self._view_mode == "grid" else "⊞")
        self.view_mode_changed.emit(self._view_mode)
        self._rebuild_cards()

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.strip().lower()
        self._rebuild_cards()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._view_mode == "grid":
            new_cols = self._calculate_columns()
            if new_cols != self._current_cols:
                self._rebuild_cards()

    def _calculate_columns(self) -> int:
        """Calculate columns based on width, minimum 1, scaling with window width."""
        w = self.scroll_area.viewport().width()
        if w < 320:
            return 1
        elif w < 540:
            return 2
        elif w < 760:
            return 3
        else:
            return max(3, w // 200)

    def _rebuild_cards(self) -> None:
        # Clear existing layout
        old_layout = self.cards_container.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            QWidget().setLayout(old_layout)

        # Filter chats
        filtered = self._chats
        if self._search_query:
            filtered = [
                c for c in self._chats
                if self._search_query in str(c.get("title", "")).lower()
                or any(self._search_query in str(m.get("content", "")).lower() for m in c.get("messages", []))
            ]

        if not filtered:
            layout = QVBoxLayout(self.cards_container)
            layout.setContentsMargins(10, 30, 10, 30)
            msg = "No matching chats found." if self._search_query else "No chat history yet.\nClick [+ New Chat] to start a stealth AI session."
            empty_lbl = QLabel(msg, self.cards_container)
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #71717a; font-size: 11px;")
            layout.addWidget(empty_lbl)
            self.cards_container.setLayout(layout)
            return

        if self._view_mode == "list":
            layout = QVBoxLayout(self.cards_container)
            layout.setContentsMargins(0, 0, 4, 0)
            layout.setSpacing(6)
            for c in filtered:
                card = ChatCard(c, is_list_view=True, parent=self.cards_container)
                card.clicked.connect(self.chat_selected.emit)
                card.delete_requested.connect(self.delete_chat_requested.emit)
                layout.addWidget(card)
            layout.addStretch()
            self.cards_container.setLayout(layout)
        else:
            cols = self._calculate_columns()
            self._current_cols = cols
            grid = QGridLayout(self.cards_container)
            grid.setContentsMargins(0, 0, 4, 0)
            grid.setSpacing(8)

            for idx, c in enumerate(filtered):
                row = idx // cols
                col = idx % cols
                card = ChatCard(c, is_list_view=False, parent=self.cards_container)
                card.clicked.connect(self.chat_selected.emit)
                card.delete_requested.connect(self.delete_chat_requested.emit)
                grid.addWidget(card, row, col)

            self.cards_container.setLayout(grid)
