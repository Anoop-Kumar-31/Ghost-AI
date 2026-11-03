"""
History and Home view for Ghost AI.
Matches the sleek modern dark UI with:
- 'Your conversations' header with '+ New chat' action button
- Search bar with 'Ctrl K' shortcut hint
- 'Recent' section with 'Sort: Newest first ↓'
- Date-grouped conversation cards ('TODAY', 'YESTERDAY', 'PREVIOUS 7 DAYS', 'OLDER')
- Topic-aware category icons (</>, 📖, 💡, 💬), titles, snippets, timestamps, and '•••' menu
- 'Load more conversations ↓' footer
Strictly preserves the standard ArrowCursor across all elements.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QScrollArea,
    QMenu,
    QInputDialog,
)

from .chat_view import NoIBeamLineEdit
from .icon_manager import get_icon, get_pixmap, COLOR_DEFAULT, COLOR_ACTIVE, COLOR_HOVER


import re

_CODE_PATTERN = re.compile(
    r"\b(react|virtual dom|javascript|js|typescript|ts|python|py|code|coding|dev|developer|api|node|sql|css|html|function|bug|git|algorithm)\b",
    re.IGNORECASE,
)
_STUDY_PATTERN = re.compile(
    r"\b(gate|notes|note|exam|study|book|graph|tree|sorting|theory|cse)\b",
    re.IGNORECASE,
)
_DESIGN_PATTERN = re.compile(
    r"\b(design|interface|ui|ux|idea|ideas|creative|concept|mockup|figma|layout)\b",
    re.IGNORECASE,
)


def get_topic_icon(title: str, snippet: str) -> str:
    """Choose an appropriate topic icon name based on title or snippet keywords."""
    combined = f"{title} {snippet}"
    if _CODE_PATTERN.search(combined):
        return "code"
    if _STUDY_PATTERN.search(combined):
        return "book-open"
    if _DESIGN_PATTERN.search(combined):
        return "lightbulb"
    return "message-square"


def format_conversation_timestamp(iso_str: str) -> str:
    """Format an ISO timestamp into a clean display time (e.g. '7:42 PM' or 'Yesterday')."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now()
        if dt.date() == now.date():
            # Format as 12-hour time
            return dt.strftime("%I:%M %p").lstrip("0")
        elif dt.date() == (now.date() - timedelta(days=1)):
            return "Yesterday"
        elif dt.year == now.year:
            return dt.strftime("%b %d")
        return dt.strftime("%m/%d/%y")
    except Exception:
        return ""


def get_date_category(iso_str: str) -> str:
    """Categorize a conversation into TODAY, YESTERDAY, PREVIOUS 7 DAYS, or OLDER."""
    if not iso_str:
        return "TODAY"
    try:
        dt = datetime.fromisoformat(iso_str).date()
        today = date.today()
        if dt == today:
            return "TODAY"
        elif dt == (today - timedelta(days=1)):
            return "YESTERDAY"
        elif dt >= (today - timedelta(days=7)):
            return "PREVIOUS 7 DAYS"
        return "OLDER"
    except Exception:
        return "TODAY"


class ConversationItem(QFrame):
    """
    A single conversation row card in the Recent list.
    Displays:
    - Rounded category icon box (</>, 📖, 💡, 💬)
    - Title and preview snippet
    - Timestamp (e.g. '7:42 PM', 'Yesterday')
    - '•••' context menu (Open, Rename, Delete)
    """

    clicked = Signal(str)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)

    def __init__(self, chat: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.chat_id = str(chat.get("id", ""))
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._title = str(chat.get("title") or "Untitled Chat")
        messages = chat.get("messages", [])
        updated_at = str(chat.get("updated_at") or chat.get("created_at") or "")

        # Snippet preview
        snippet = "Your conversation workspace."
        if messages:
            last_msg = messages[-1]
            content = str(last_msg.get("content", "")).strip().replace("\n", " ")
            if content:
                snippet = content[:65] + "..." if len(content) > 65 else content

        icon_char = get_topic_icon(self._title, snippet)
        time_str = format_conversation_timestamp(updated_at)

        self._init_ui(icon_char, self._title, snippet, time_str)
        self._apply_style()

    def _init_ui(self, icon_char: str, title: str, snippet: str, time_str: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # 1. Topic Icon Box
        self.icon_frame = QFrame(self)
        self.icon_frame.setFixedSize(38, 38)
        self.icon_frame.setCursor(Qt.CursorShape.ArrowCursor)
        self.icon_frame.setStyleSheet(
            """
            QFrame {
                background-color: #1a1926;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 8px;
            }
            """
        )
        icon_layout = QVBoxLayout(self.icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        topic_colors = {
            "code": "#c4b5fd",          # soft violet
            "book-open": "#60a5fa",     # soft blue
            "lightbulb": "#fbbf24",     # soft amber
            "message-square": "#9ca3af", # soft neutral gray
        }
        icon_color = topic_colors.get(icon_char, "#9ca3af")

        icon_lbl = QLabel(self.icon_frame)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(get_pixmap(icon_char, 18, icon_color))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_layout.addWidget(icon_lbl)
        layout.addWidget(self.icon_frame)

        # 2. Text Column (Title & Snippet)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.title_lbl.setStyleSheet(
            "color: #f4f4f5; font-size: 13px; font-weight: 600; background: transparent;"
        )
        text_col.addWidget(self.title_lbl)

        self.snippet_lbl = QLabel(snippet, self)
        self.snippet_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        self.snippet_lbl.setStyleSheet("color: #828290; font-size: 11px; background: transparent;")
        text_col.addWidget(self.snippet_lbl)

        layout.addLayout(text_col, 1)

        # 3. Right Column: Timestamp & '•••' Menu
        right_col = QHBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        if time_str:
            self.time_lbl = QLabel(time_str, self)
            self.time_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.time_lbl.setStyleSheet("color: #6b7280; font-size: 11px; background: transparent;")
            right_col.addWidget(self.time_lbl)

        # '•••' Action Menu Button
        self.menu_btn = QPushButton(self)
        self.menu_btn.setFixedSize(24, 24)
        self.menu_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.menu_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu_btn.setIcon(get_icon("more-horizontal", 14, "#71717a"))
        self.menu_btn.setIconSize(QSize(14, 14))
        self.menu_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
            }
            """
        )
        self.menu_btn.clicked.connect(self._show_context_menu)
        right_col.addWidget(self.menu_btn)

        layout.addLayout(right_col)

    def _apply_style(self) -> None:
        self.setObjectName("ConversationItem")
        self.setStyleSheet(
            """
            QFrame#ConversationItem {
                background-color: transparent;
                border: none;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 6px;
            }
            QFrame#ConversationItem:hover {
                background-color: rgba(255, 255, 255, 0.03);
            }
            """
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.chat_id)
        super().mousePressEvent(event)

    def _show_context_menu(self) -> None:
        menu = QMenu(self)
        menu.setCursor(Qt.CursorShape.ArrowCursor)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #181824;
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #271a47;
                color: #ffffff;
            }
            """
        )

        open_action = menu.addAction(get_icon("message-square", 14, "#c4b5fd"), "Open")
        rename_action = menu.addAction(get_icon("pencil", 14, "#c4b5fd"), "Rename")
        menu.addSeparator()
        delete_action = menu.addAction(get_icon("trash-2", 14, "#f87171"), "Delete")

        pos = self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height()))
        selected = menu.exec(pos)

        if selected == open_action:
            self.clicked.emit(self.chat_id)
        elif selected == rename_action:
            new_title, ok = QInputDialog.getText(
                self, "Rename Conversation", "New title:", text=self._title
            )
            if ok and new_title.strip():
                self.rename_requested.emit(self.chat_id, new_title.strip())
        elif selected == delete_action:
            self.delete_requested.emit(self.chat_id)


class HistoryView(QWidget):
    """
    Home page displaying the sleek modern dark conversation list.
    Features:
    - 'Your conversations' title & '+ New chat' action button
    - Search input with 'Ctrl K' hint
    - Date grouping ('TODAY', 'YESTERDAY', 'PREVIOUS 7 DAYS', 'OLDER')
    - Conversation cards with topic icons, snippets, relative times, and options menu
    """

    chat_selected = Signal(str)
    new_chat_requested = Signal()
    delete_chat_requested = Signal(str)
    settings_requested = Signal()
    view_mode_changed = Signal(str)
    chat_renamed = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._chats: List[Dict[str, Any]] = []
        self._view_mode: str = "list"
        self._search_query: str = ""
        self._sort_mode: str = "newest"  # "newest", "oldest", "title"

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(14)

        # 1. Top Section: Title & Subtitle + '+ New chat' Button
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        self.main_title_lbl = QLabel("Your conversations", self)
        self.main_title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 22px; font-weight: 700; background: transparent;"
        )
        title_col.addWidget(self.main_title_lbl)

        self.subtitle_lbl = QLabel("All your thoughts, in one place.", self)
        self.subtitle_lbl.setStyleSheet(
            "color: #71717a; font-size: 13px; background: transparent;"
        )
        title_col.addWidget(self.subtitle_lbl)
        header_row.addLayout(title_col, 1)

        # '+ New chat' Button
        self.new_chat_btn = QPushButton(" New chat", self)
        self.new_chat_btn.setIcon(get_icon("plus", 14, "#ffffff"))
        self.new_chat_btn.setIconSize(QSize(14, 14))
        self.new_chat_btn.setFixedSize(100, 34)
        self.new_chat_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.new_chat_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.new_chat_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #8b5cf6;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #7c3aed;
            }
            QPushButton:pressed {
                background-color: #6d28d9;
            }
            """
        )
        self.new_chat_btn.clicked.connect(self.new_chat_requested.emit)
        header_row.addWidget(self.new_chat_btn)

        # Legacy view toggle button for backward compatibility with tests
        self.toggle_view_btn = QPushButton("☰", self)
        self.toggle_view_btn.hide()

        main_layout.addLayout(header_row)

        # 2. Search Bar
        search_card = QFrame(self)
        search_card.setCursor(Qt.CursorShape.ArrowCursor)
        search_card.setFixedHeight(40)
        search_card.setStyleSheet(
            """
            QFrame {
                background-color: #14141e;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            """
        )
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(12, 0, 12, 0)
        search_layout.setSpacing(8)

        search_icon = QLabel(search_card)
        search_icon.setPixmap(get_pixmap("search", 14, "#6b7280"))
        search_icon.setStyleSheet("background: transparent; border: none;")
        search_layout.addWidget(search_icon)

        self.search_edit = NoIBeamLineEdit(search_card)
        self.search_edit.setPlaceholderText("Search your conversations...")
        self.search_edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                color: #f4f4f5;
                font-size: 12px;
            }
            """
        )
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_edit, 1)

        shortcut_badge = QLabel("Ctrl K", search_card)
        shortcut_badge.setStyleSheet(
            "color: #52525b; font-size: 11px; background: transparent; font-weight: 500; border:none;"
        )
        search_layout.addWidget(shortcut_badge)

        main_layout.addWidget(search_card)

        # 3. Section Header: 'Recent' + 'Sort: Newest first ↓'
        section_row = QHBoxLayout()
        section_row.setContentsMargins(0, 4, 0, 0)
        section_row.setSpacing(8)

        recent_lbl = QLabel("Recent", self)
        recent_lbl.setStyleSheet(
            "color: #ffffff; font-size: 13px; font-weight: 700; background: transparent;"
        )
        section_row.addWidget(recent_lbl)

        section_row.addStretch(1)

        self.sort_btn = QPushButton("Sort: Newest first ↓", self)
        self.sort_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.sort_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sort_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #9ca3af;
                border: none;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
            """
        )
        self.sort_btn.clicked.connect(self._toggle_sort_mode)
        section_row.addWidget(self.sort_btn)

        main_layout.addLayout(section_row)

        # 4. Scrollable Container for Conversation Cards
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
                background: transparent;
                width: 6px;
                margin: 0px;
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
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(4)
        self.cards_layout.addStretch(1)

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, 1)

        # 5. Footer: 'Load more conversations'
        self.load_more_btn = QPushButton(" Load more conversations", self)
        self.load_more_btn.setIcon(get_icon("chevron-down", 12, "#71717a"))
        self.load_more_btn.setIconSize(QSize(12, 12))
        self.load_more_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.load_more_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.load_more_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #71717a;
                border: none;
                font-size: 11px;
                padding: 6px;
            }
            QPushButton:hover {
                color: #a1a1aa;
            }
            """
        )
        self.load_more_btn.clicked.connect(self._on_load_more_clicked)
        main_layout.addWidget(self.load_more_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def set_chats(self, chats: List[Dict[str, Any]], view_mode: str = "list") -> None:
        """Update chats list and rebuild grouped conversation rows."""
        self._chats = chats
        self._view_mode = view_mode
        self._rebuild_cards()

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self.view_mode_changed.emit(self._view_mode)

    def _toggle_sort_mode(self) -> None:
        if self._sort_mode == "newest":
            self._sort_mode = "oldest"
            self.sort_btn.setText("Sort: Oldest first ↑")
        elif self._sort_mode == "oldest":
            self._sort_mode = "title"
            self.sort_btn.setText("Sort: Title A-Z ↓")
        else:
            self._sort_mode = "newest"
            self.sort_btn.setText("Sort: Newest first ↓")
        self._rebuild_cards()

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.strip().lower()
        self._rebuild_cards()

    def _on_load_more_clicked(self) -> None:
        # Currently displays all saved chats; provides responsive click feedback
        self.load_more_btn.setText("All conversations loaded")

    def _rebuild_cards(self) -> None:
        # Clear existing items from cards layout
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Filter by search
        filtered = []
        for chat in self._chats:
            title = str(chat.get("title", "")).lower()
            snippet = ""
            msgs = chat.get("messages", [])
            if msgs:
                snippet = str(msgs[-1].get("content", "")).lower()
            if not self._search_query or (self._search_query in title or self._search_query in snippet):
                filtered.append(chat)

        # Sort
        if self._sort_mode == "title":
            filtered.sort(key=lambda c: str(c.get("title", "")).lower())
        elif self._sort_mode == "oldest":
            filtered.sort(key=lambda c: str(c.get("updated_at") or c.get("created_at") or ""))
        else:
            # newest first (default)
            filtered.sort(key=lambda c: str(c.get("updated_at") or c.get("created_at") or ""), reverse=True)

        if not filtered:
            empty_lbl = QLabel(
                "No conversations found.\nClick '+ New chat' to begin."
                if self._search_query
                else "No conversations yet.\nClick '+ New chat' to begin.",
                self.cards_container,
            )
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet(
                "color: #71717a; font-size: 12px; padding: 40px; background: transparent;"
            )
            self.cards_layout.addWidget(empty_lbl)
            self.cards_layout.addStretch(1)
            self.load_more_btn.hide()
            return

        self.load_more_btn.show()

        # Group by category (TODAY, YESTERDAY, PREVIOUS 7 DAYS, OLDER)
        groups: Dict[str, List[Dict[str, Any]]] = {
            "TODAY": [],
            "YESTERDAY": [],
            "PREVIOUS 7 DAYS": [],
            "OLDER": [],
        }

        for chat in filtered:
            cat = get_date_category(str(chat.get("updated_at") or chat.get("created_at") or ""))
            groups[cat].append(chat)

        for cat_name in ("TODAY", "YESTERDAY", "PREVIOUS 7 DAYS", "OLDER"):
            cat_chats = groups[cat_name]
            if not cat_chats:
                continue

            # Section Header (TODAY, YESTERDAY, etc.)
            cat_lbl = QLabel(cat_name, self.cards_container)
            cat_lbl.setStyleSheet(
                "color: #6b7280; font-size: 11px; font-weight: 700; letter-spacing: 1px; "
                "padding-top: 14px; padding-bottom: 4px; background: transparent;"
            )
            self.cards_layout.addWidget(cat_lbl)

            # Items inside category
            for chat in cat_chats:
                item = ConversationItem(chat, parent=self.cards_container)
                item.clicked.connect(self.chat_selected.emit)
                item.delete_requested.connect(self.delete_chat_requested.emit)
                item.rename_requested.connect(self._on_item_renamed)
                self.cards_layout.addWidget(item)

        self.cards_layout.addStretch(1)

    def _on_item_renamed(self, chat_id: str, new_title: str) -> None:
        self.chat_renamed.emit(chat_id, new_title)
