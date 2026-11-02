"""
Chat room view for Ghost AI.
Matches the sleek modern dark workspace UI:
- Large bold conversation title & 'Your conversation workspace.' subtitle
- User & AI message bubbles with markdown and Pygments syntax highlighting
- Sleek integrated prompt input card with:
  - 'Ask anything...' multiline auto-expanding text editor
  - '📎' attachment button, '🎙️' microphone, and '🔊' system/meeting loopback audio buttons
  - Green model selector pill (e.g. 'Claude', 'GPT-4o-mini')
  - Circular '↑' send button
Strictly preserves the standard ArrowCursor across all elements.
"""

import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QGuiApplication,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QTextBrowser,
    QScrollArea,
    QPushButton,
    QFrame,
    QSizePolicy,
    QFileDialog,
)

from .config import load_config
from .ai_service import AIChatWorker
from .voice_worker import MicVoiceWorker, SysAudioWorker
from .markdown_renderer import render_markdown, render_full_html, get_document_css
from .icon_manager import (
    get_icon,
    get_pixmap,
    IconButton,
    COLOR_DEFAULT,
    COLOR_ACTIVE,
    COLOR_HOVER,
)


class NoIBeamLineEdit(QLineEdit):
    """QLineEdit strictly preserving the ArrowCursor."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        try:
            super().enterEvent(event)
        except Exception:
            pass

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        try:
            super().mouseMoveEvent(event)
        except Exception:
            pass


class ChatInputEdit(QTextEdit):
    """
    Auto-expanding input area that sends on Enter and adds newline on Shift+Enter.
    Maintains ArrowCursor strictly.
    """

    send_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask anything...")
        self.setFixedHeight(30)
        self.textChanged.connect(self._adjust_height)

        self.setStyleSheet(
            """
            QTextEdit {
                background: transparent;
                color: #f4f4f5;
                border: none;
                padding: 4px 0px;
                font-size: 10px;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            """
        )

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                event.accept()
                self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def _adjust_height(self) -> None:
        doc_height = int(self.document().size().height())
        new_height = max(36, min(140, doc_height + 10))
        self.setFixedHeight(new_height)


class MarkdownBrowser(QTextBrowser):
    """
    QTextBrowser for rendering Markdown content cleanly with stealth ArrowCursor
    and dynamic auto-height to prevent nested scrollbars.
    Uses centralized ghost_ai.markdown_renderer (markdown-it-py + Pygments).
    """

    def __init__(self, content: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        self.setStyleSheet(
            """
            QTextBrowser {
                color: #f4f4f5;
                background: transparent;
                border: none;
                font-size: 11px;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            """
        )
        self.document().setDefaultStyleSheet(get_document_css())

        if content:
            self.set_content(content)

    def set_content(self, md: str) -> None:
        """Render Markdown through centralized markdown_renderer."""
        html = render_full_html(md)
        self.setHtml(html)
        self.adjust_height()

    def setMarkdown(self, markdown: str) -> None:
        """Override to route through our centralized renderer."""
        self.set_content(markdown)

    def adjust_height(self) -> None:
        vw = self.viewport().width()
        if vw > 20:
            self.document().setTextWidth(vw)
        doc_h = int(self.document().documentLayout().documentSize().height())
        self.setFixedHeight(max(24, doc_h + 6))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.adjust_height()

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


class MessageBubble(QFrame):
    """
    Message bubble widget with markdown rendering and stealth ArrowCursor.
    User bubbles are dark purple-tinted and aligned right.
    AI bubbles are left-aligned with syntax highlighting and a copy button.
    """

    def __init__(
        self,
        role: str,
        content: str,
        timestamp: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 8, 5, 8)
        layout.setSpacing(4)

        # Header row (sender name + timestamp + copy button)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        sender_text = "You" if self.role == "user" else "Ghost AI"
        self.sender_lbl = QLabel(sender_text, self)
        self.sender_lbl.setCursor(Qt.CursorShape.ArrowCursor)

        if self.role == "user":
            self.sender_lbl.setStyleSheet("color: #a78bfa; font-size: 10px; font-weight: 700; background: transparent;")
        else:
            self.sender_lbl.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 700; background: transparent;")
        header_row.addWidget(self.sender_lbl)

        header_row.addStretch()

        # Copy button
        self.copy_btn = QPushButton(self)
        self.copy_btn.setFixedSize(26, 20)
        self.copy_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.setToolTip("Copy response")
        self.copy_btn.setIcon(get_icon("copy", 12, "#71717a"))
        self.copy_btn.setIconSize(QSize(12, 12))
        self.copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
            }
            """
        )
        self.copy_btn.clicked.connect(self._copy_content)
        header_row.addWidget(self.copy_btn)

        layout.addLayout(header_row)

        # Content area
        if self.role == "user":
            self.text_lbl = QLabel(self.content, self)
            self.text_lbl.setWordWrap(True)
            self.text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.text_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.text_lbl.setStyleSheet(
                """
                QLabel {
                    color: #f4f4f5;
                    font-size: 11px;
                    line-height: 1.45;
                    background: transparent;
                    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                }
                """
            )
            layout.addWidget(self.text_lbl)
        else:
            self.text_lbl = MarkdownBrowser(self.content, self)
            layout.addWidget(self.text_lbl)

        # Style bubble background
        if self.role == "user":
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: #1e192f;
                    border: 1px solid rgba(139, 92, 246, 0.25);
                    border-radius: 12px;
                }
                """
            )
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        else:
            self.setStyleSheet(
                """
                MessageBubble {
                    background-color: rgba(24, 24, 27, 0.75);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                }
                """
            )
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def update_content(self, text: str) -> None:
        """Update live streamed Markdown content."""
        self.content = text
        if self.role == "user":
            if isinstance(self.text_lbl, QLabel):
                self.text_lbl.setText(text)
        else:
            if isinstance(self.text_lbl, MarkdownBrowser):
                self.text_lbl.set_content(text)

    def _copy_content(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.content)
            self.copy_btn.setIcon(get_icon("circle-check", 12, "#10b981"))
            QTimer.singleShot(1500, lambda: self.copy_btn.setIcon(get_icon("copy", 12, "#71717a")))


class ChatView(QWidget):
    """
    Chat conversation view matching the modern workspace UI in Screenshot 2.
    """

    home_requested = Signal()
    new_chat_requested = Signal()
    settings_requested = Signal()
    chat_updated = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._active_chat: Optional[Dict[str, Any]] = None
        self._current_worker: Optional[AIChatWorker] = None
        self._streaming_bubble: Optional[MessageBubble] = None
        self._mic_worker: Optional[MicVoiceWorker] = None
        self._sys_worker: Optional[SysAudioWorker] = None

        # Streaming render debounce (75ms)
        self._streaming_buffer: str = ""
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(75)
        self._stream_timer.timeout.connect(self._flush_stream_buffer)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 0, 5, 5)
        main_layout.setSpacing(5)

        # 1. Header Section: Title & Subtitle
        header_col = QVBoxLayout()
        header_col.setContentsMargins(0, 0, 0, 0)
        header_col.setSpacing(0)

        self.title_edit = NoIBeamLineEdit(self)
        self.title_edit.setPlaceholderText("Untitled Chat")
        self.title_edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                padding: 0px;
            }
            QLineEdit:hover, QLineEdit:focus {
                color: #c4b5fd;
            }
            """
        )
        self.title_edit.editingFinished.connect(self._on_title_edited)
        header_col.addWidget(self.title_edit)

        # self.subtitle_lbl = QLabel("Your conversation below.", self)
        # self.subtitle_lbl.setStyleSheet(
        #     "color: #71717a; font-size: 10px; background: transparent;"
        # )
        # header_col.addWidget(self.subtitle_lbl)

        main_layout.addLayout(header_col)

        # Compatibility buttons (hidden, provided so test_ui.py won't fail if referenced)
        self.home_btn = QPushButton("⌂ Chats", self)
        self.home_btn.hide()
        self.home_btn.clicked.connect(self.home_requested.emit)

        self.new_btn = QPushButton("+", self)
        self.new_btn.hide()
        self.new_btn.clicked.connect(self.new_chat_requested.emit)

        self.settings_btn = QPushButton("⚙", self)
        self.settings_btn.hide()
        self.settings_btn.clicked.connect(self.settings_requested.emit)

        # 2. API Key Warning Banner (hidden when key is configured)
        self.banner = QFrame(self)
        self.banner.setObjectName("ApiKeyBanner")
        self.banner.setStyleSheet(
            """
            QFrame#ApiKeyBanner {
                background-color: rgba(180, 83, 9, 0.25);
                border: 1px solid rgba(245, 158, 11, 0.35);
                border-radius: 8px;
                padding: 4px;
            }
            """
        )
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(10, 4, 10, 4)
        banner_lbl = QLabel("⚠️ API Key not configured. Click Settings to enter key.", self.banner)
        banner_lbl.setStyleSheet("color: #fcd34d; font-size: 11px; background: transparent;")
        banner_layout.addWidget(banner_lbl)
        banner_layout.addStretch()
        cfg_btn = QPushButton("Configure", self.banner)
        cfg_btn.setFixedSize(68, 22)
        cfg_btn.setCursor(Qt.CursorShape.ArrowCursor)
        cfg_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #d97706;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #b45309;
            }
            """
        )
        cfg_btn.clicked.connect(self.settings_requested.emit)
        banner_layout.addWidget(cfg_btn)
        main_layout.addWidget(self.banner)
        self.check_api_key_banner()

        # 3. Scrollable Message Area
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

        self.messages_container = QWidget()
        self.messages_container.setCursor(Qt.CursorShape.ArrowCursor)
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(0, 4, 0, 4)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)

        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, 1)

        # 4. Voice Status Banner
        self.voice_status_frame = QFrame(self)
        self.voice_status_frame.setObjectName("VoiceStatusBanner")
        self.voice_status_frame.setStyleSheet(
            """
            QFrame#VoiceStatusBanner {
                background-color: #1a1926;
                border: 1px solid rgba(139, 92, 246, 0.3);
                border-radius: 8px;
                padding: 2px 6px;
            }
            """
        )
        vs_layout = QHBoxLayout(self.voice_status_frame)
        vs_layout.setContentsMargins(10, 4, 10, 4)
        vs_layout.setSpacing(2)

        self.voice_status_lbl = QLabel(self.voice_status_frame)
        self.voice_status_lbl.setStyleSheet(
            "color: #c4b5fd; font-size: 11px; font-weight: 500; background: transparent;"
        )
        vs_layout.addWidget(self.voice_status_lbl, 1)

        self.voice_cancel_btn = QPushButton("✕", self.voice_status_frame)
        self.voice_cancel_btn.setFixedSize(18, 18)
        self.voice_cancel_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.voice_cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #a1a1aa; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #ffffff; }"
        )
        self.voice_cancel_btn.clicked.connect(self._cancel_voice_recording)
        vs_layout.addWidget(self.voice_cancel_btn)

        self.voice_status_frame.hide()
        main_layout.addWidget(self.voice_status_frame)

        # 5. Modern Integrated Input Card (ChatGPT / Claude style)
        self.input_card = QFrame(self)
        self.input_card.setObjectName("ChatInputCard")
        self.input_card.setCursor(Qt.CursorShape.ArrowCursor)
        self.input_card.setStyleSheet(
            """
            QFrame#ChatInputCard {
                background-color: #121218;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                padding: 10px 14px;
            }
            QFrame#ChatInputCard:focus-within {
                border: 1px solid rgba(139, 92, 246, 0.5);
            }
            """
        )
        card_layout = QVBoxLayout(self.input_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(8)

        # Top of card: Multiline text input
        self.input_edit = ChatInputEdit(self.input_card)
        self.input_edit.send_requested.connect(self._on_send_clicked)
        card_layout.addWidget(self.input_edit)

        # Bottom row of card: Action controls
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(2)

        # Attachment button (paperclip)
        self.attach_btn = IconButton(
            "paperclip",
            size=16,
            btn_size=28,
            color_default=COLOR_DEFAULT,
            color_hover=COLOR_HOVER,
            tooltip="Attach context / file",
            parent=self.input_card,
        )
        self.attach_btn.clicked.connect(self._on_attach_clicked)
        bottom_row.addWidget(self.attach_btn)

        # Microphone voice button
        self.mic_btn = QPushButton(self.input_card)
        self.mic_btn.setFixedSize(28, 28)
        self.mic_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.mic_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mic_btn.setToolTip("Record Microphone (Speech-to-Text)")
        self.mic_btn.setIcon(get_icon("mic", 16, COLOR_DEFAULT))
        self.mic_btn.setIconSize(QSize(16, 16))
        self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
        self.mic_btn.clicked.connect(self._toggle_mic_recording)
        bottom_row.addWidget(self.mic_btn)

        # System audio loopback button
        self.sys_audio_btn = QPushButton(self.input_card)
        self.sys_audio_btn.setFixedSize(28, 28)
        self.sys_audio_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.sys_audio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sys_audio_btn.setToolTip("Capture Meeting Audio (Google Meet / Zoom)")
        self.sys_audio_btn.setIcon(get_icon("volume-2", 16, COLOR_DEFAULT))
        self.sys_audio_btn.setIconSize(QSize(16, 16))
        self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())
        self.sys_audio_btn.clicked.connect(self._toggle_sys_audio_recording)
        bottom_row.addWidget(self.sys_audio_btn)

        bottom_row.addStretch(1)

        # Model badge pill (e.g. 'Claude', 'GPT-4o-mini')
        self.model_badge = QPushButton("Claude", self.input_card)
        self.model_badge.setCursor(Qt.CursorShape.ArrowCursor)
        self.model_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.model_badge.setToolTip("Current AI Model (Click to configure)")
        self.model_badge.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(16, 185, 129, 0.12);
                color: #10b981;
                border: 1px solid rgba(16, 185, 129, 0.25);
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(16, 185, 129, 0.2);
                border-color: rgba(16, 185, 129, 0.4);
            }
            """
        )
        self.model_badge.clicked.connect(self.settings_requested.emit)
        bottom_row.addWidget(self.model_badge)

        # Circular send button '↑'
        self.send_btn = QPushButton(self.input_card)
        self.send_btn.setFixedSize(28, 28)
        self.send_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.send_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.send_btn.setToolTip("Send message (Enter)")
        self.send_btn.setIcon(get_icon("arrow-up", 16, "#ffffff"))
        self.send_btn.setIconSize(QSize(16, 16))
        self.send_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #1e1e28;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
            QPushButton:hover {
                background-color: #7c3aed;
                border-color: #8b5cf6;
            }
            """
        )
        self.send_btn.clicked.connect(self._on_send_clicked)
        bottom_row.addWidget(self.send_btn)

        card_layout.addLayout(bottom_row)
        main_layout.addWidget(self.input_card)

        self._update_model_badge()

    def _update_model_badge(self) -> None:
        """Update model pill text based on current configuration."""
        if not hasattr(self, "model_badge") or self.model_badge is None:
            return
        cfg = load_config()
        model_name = cfg.get("model", "Claude")
        # Simplify display name for clean badge
        if "claude" in model_name.lower():
            display = "Claude"
        elif "gpt-4o" in model_name.lower():
            display = "GPT-4o"
        elif "deepseek" in model_name.lower():
            display = "DeepSeek"
        elif "llama" in model_name.lower():
            display = "Llama"
        elif "gemini" in model_name.lower():
            display = "Gemini"
        else:
            display = model_name.split("/")[-1].split(":")[0]
            if len(display) > 12:
                display = display[:10] + "…"
        self.model_badge.setText(display)

    def _on_attach_clicked(self) -> None:
        """Open file dialog to attach text or code file into prompt."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach file", "", "Text files (*.txt *.md *.py *.js *.ts *.json *.html *.css);;All files (*.*)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(4000)
                cur = self.input_edit.toPlainText().strip()
                prefix = f"--- Context from {path.split('/')[-1]} ---\n{content}\n---\n"
                self.input_edit.setPlainText(f"{prefix}\n{cur}" if cur else prefix)
                self.input_edit.setFocus()
            except Exception:
                pass

    def check_api_key_banner(self) -> None:
        """Show banner if no API key is present."""
        cfg = load_config()
        key = cfg.get("api_key", "").strip()
        base_url = cfg.get("base_url", "")
        is_local = "localhost" in base_url or "127.0.0.1" in base_url
        if key or is_local:
            self.banner.hide()
        else:
            self.banner.show()
        self._update_model_badge()

    def set_active_chat(self, chat: Dict[str, Any]) -> None:
        """Load and display the given chat session."""
        self._active_chat = chat
        title = chat.get("title", "Untitled Chat")
        self.title_edit.setText(title)
        self._clear_messages_display()

        messages = chat.get("messages", [])
        if not messages:
            empty_lbl = QLabel(
                "💬 Start a conversation with Ghost AI.\n"
                "Responses are streaming, encrypted in transit, and completely invisible to screen capture.",
                self.messages_container,
            )
            empty_lbl.setObjectName("EmptyChatPlaceholder")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet(
                "color: #71717a; font-size: 11px; padding: 30px 10px; background: transparent;"
            )
            self.messages_layout.insertWidget(0, empty_lbl)
        else:
            for m in messages:
                bubble = MessageBubble(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                    timestamp=m.get("timestamp", ""),
                    parent=self.messages_container,
                )
                self._add_bubble_row(bubble)

        self._scroll_to_bottom()
        self.check_api_key_banner()

    def _clear_messages_display(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def _add_bubble_row(self, bubble: MessageBubble) -> None:
        """Wrap a bubble in a row widget so user bubbles sit right and AI bubbles sit left."""
        row = QWidget(self.messages_container)
        row.setCursor(Qt.CursorShape.ArrowCursor)
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if bubble.role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble, 0)
        else:
            row_layout.addWidget(bubble, 1)
            row_layout.addStretch(0)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, row)

    def _on_title_edited(self) -> None:
        if not self._active_chat:
            return
        new_title = self.title_edit.text().strip() or "Untitled Chat"
        self._active_chat["title"] = new_title
        self._active_chat["updated_at"] = datetime.now().isoformat()
        self.chat_updated.emit()

    def _on_send_clicked(self) -> None:
        if self._current_worker and self._current_worker.isRunning():
            self._stream_timer.stop()
            self._current_worker.cancel()
            self._set_generating_state(False)
            return

        text = self.input_edit.toPlainText().strip()
        if not text or not self._active_chat:
            return

        self.input_edit.clear()

        # Remove placeholder if present
        placeholder = self.messages_container.findChild(QLabel, "EmptyChatPlaceholder")
        if placeholder:
            placeholder.deleteLater()

        now_iso = datetime.now().isoformat()
        user_msg = {"role": "user", "content": text, "timestamp": now_iso}
        if "messages" not in self._active_chat:
            self._active_chat["messages"] = []
        self._active_chat["messages"].append(user_msg)

        # Auto-name title if currently "New Chat" or "Untitled Chat"
        cur_title = self._active_chat.get("title", "")
        if cur_title in ("New Chat", "Untitled Chat", ""):
            derived = text.splitlines()[0][:28].strip()
            if len(text) > 28:
                derived += "..."
            self._active_chat["title"] = derived
            self.title_edit.setText(derived)

        self._active_chat["updated_at"] = now_iso
        self.chat_updated.emit()

        user_bubble = MessageBubble("user", text, now_iso, self.messages_container)
        self._add_bubble_row(user_bubble)

        # Prepare AI response placeholder
        self._streaming_bubble = MessageBubble("assistant", "...", now_iso, self.messages_container)
        self._add_bubble_row(self._streaming_bubble)
        self._scroll_to_bottom()

        # Start background worker and debounce timer
        self._streaming_buffer = ""
        self._stream_timer.start()

        cfg = load_config()
        self._current_worker = AIChatWorker(self._active_chat["messages"], cfg, self)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.finished.connect(self._on_generation_finished)
        self._current_worker.error.connect(self._on_generation_error)

        self._set_generating_state(True)
        self._current_worker.start()

    def _set_generating_state(self, generating: bool) -> None:
        if generating:
            self.send_btn.setIcon(get_icon("square", 13, "#ffffff"))
            self.send_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #dc2626;
                    border: 1px solid #ef4444;
                    border-radius: 14px;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                }
                """
            )
        else:
            self.send_btn.setIcon(get_icon("arrow-up", 16, "#ffffff"))
            self.send_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #1e1e28;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 14px;
                }
                QPushButton:hover {
                    background-color: #7c3aed;
                    border-color: #8b5cf6;
                }
                """
            )

    def _on_chunk_received(self, chunk: str) -> None:
        if not self._streaming_bubble:
            return
        if self._streaming_buffer == "...":
            self._streaming_buffer = chunk
        else:
            self._streaming_buffer += chunk

    def _flush_stream_buffer(self) -> None:
        if self._streaming_bubble and self._streaming_buffer:
            self._streaming_bubble.update_content(self._streaming_buffer)
            self._scroll_to_bottom()

    def _on_generation_finished(self, full_response: str) -> None:
        self._stream_timer.stop()
        self._set_generating_state(False)
        if not self._active_chat or not self._streaming_bubble:
            return

        final_text = full_response if full_response else self._streaming_buffer
        if not final_text or final_text == "...":
            final_text = "(Empty response)"
        self._streaming_bubble.update_content(final_text)
        self._streaming_buffer = ""

        now_iso = datetime.now().isoformat()
        ai_msg = {"role": "assistant", "content": final_text, "timestamp": now_iso}
        self._active_chat["messages"].append(ai_msg)
        self._active_chat["updated_at"] = now_iso
        self.chat_updated.emit()
        self._scroll_to_bottom()

    def _on_generation_error(self, err_msg: str) -> None:
        self._stream_timer.stop()
        self._set_generating_state(False)
        if self._streaming_bubble:
            self._streaming_bubble.update_content(f"⚠️ {err_msg}")
        self._streaming_buffer = ""
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Voice-to-Text (Microphone & System/Meeting Audio WASAPI Loopback)
    # ------------------------------------------------------------------
    @staticmethod
    def _mic_btn_idle_style() -> str:
        return """
            QPushButton {
                background: transparent;
                color: #a1a1aa;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
                border-radius: 6px;
            }
        """

    @staticmethod
    def _mic_btn_active_style() -> str:
        return """
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border: 1px solid #ef4444;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """

    @staticmethod
    def _sys_audio_btn_idle_style() -> str:
        return """
            QPushButton {
                background: transparent;
                color: #a1a1aa;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
                border-radius: 6px;
            }
        """

    @staticmethod
    def _sys_audio_btn_active_style() -> str:
        return """
            QPushButton {
                background-color: #7c3aed;
                color: #ffffff;
                border: 1px solid #8b5cf6;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
        """

    def _toggle_mic_recording(self) -> None:
        if self._mic_worker and self._mic_worker.isRunning():
            self.voice_status_lbl.setText("⏳ Transcribing microphone audio with Whisper AI...")
            self.mic_btn.setText("⏳")
            self._mic_worker.stop()
            return

        if self._sys_worker and self._sys_worker.isRunning():
            self._cancel_voice_recording()

        self._mic_worker = MicVoiceWorker(self)
        self._mic_worker.transcribed.connect(self._on_mic_transcribed)
        self._mic_worker.error.connect(self._on_voice_error)
        self._mic_worker.status.connect(self._on_voice_status)

        self.mic_btn.setText("⏹")
        self.mic_btn.setStyleSheet(self._mic_btn_active_style())
        self.voice_status_lbl.setText("🎙️ Recording mic... Speak clearly, click ⏹ when done.")
        self.voice_status_frame.show()
        self._mic_worker.start()

    def _toggle_sys_audio_recording(self) -> None:
        if self._sys_worker and self._sys_worker.isRunning():
            self.voice_status_lbl.setText("⏳ Transcribing meeting audio with Whisper AI...")
            self.sys_audio_btn.setText("⏳")
            self._sys_worker.stop()
            return

        if self._mic_worker and self._mic_worker.isRunning():
            self._cancel_voice_recording()

        self._sys_worker = SysAudioWorker(self)
        self._sys_worker.transcribed.connect(self._on_sys_transcribed)
        self._sys_worker.error.connect(self._on_voice_error)
        self._sys_worker.status.connect(self._on_voice_status)

        self.sys_audio_btn.setText("⏹")
        self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_active_style())
        self.voice_status_lbl.setText("🔊 Capturing system audio (Google Meet / Zoom)... Click ⏹ when done.")
        self.voice_status_frame.show()
        self._sys_worker.start()

    def _on_mic_transcribed(self, text: str) -> None:
        text = text.strip()
        if text:
            cur = self.input_edit.toPlainText().strip()
            if cur:
                self.input_edit.setPlainText(f"{cur} {text}")
            else:
                self.input_edit.setPlainText(text)
            self.input_edit.setFocus()
            self.voice_status_lbl.setText("✅ Speech transcribed to prompt!")
            QTimer.singleShot(2500, self.voice_status_frame.hide)
        else:
            self.voice_status_lbl.setText("ℹ️ No clear speech detected.")
            QTimer.singleShot(2500, self.voice_status_frame.hide)
        self._reset_voice_buttons()

    def _on_sys_transcribed(self, text: str) -> None:
        text = text.strip()
        if text:
            prefix = "Interviewer asked: "
            cur = self.input_edit.toPlainText().strip()
            if cur:
                self.input_edit.setPlainText(f"{cur}\n\n{prefix}{text}")
            else:
                self.input_edit.setPlainText(f"{prefix}{text}")
            self.input_edit.setFocus()
            self.voice_status_lbl.setText("✅ Interviewer audio transcribed!")
            QTimer.singleShot(2500, self.voice_status_frame.hide)
        else:
            self.voice_status_lbl.setText("ℹ️ No meeting audio detected.")
            QTimer.singleShot(2500, self.voice_status_frame.hide)
        self._reset_voice_buttons()

    def _on_voice_error(self, err_msg: str) -> None:
        self._reset_voice_buttons()
        self.voice_status_lbl.setText(f"⚠️ {err_msg}")
        self.voice_status_frame.show()

    def _on_voice_status(self, st: str) -> None:
        if st == "transcribing":
            self.voice_status_lbl.setText("⏳ Transcribing audio with local Whisper AI...")

    def _cancel_voice_recording(self) -> None:
        if self._mic_worker and self._mic_worker.isRunning():
            self._mic_worker.stop()
            self._mic_worker.wait(1000)
        if self._sys_worker and self._sys_worker.isRunning():
            self._sys_worker.stop()
            self._sys_worker.wait(1000)
        self._reset_voice_buttons()
        self.voice_status_frame.hide()

    def _reset_voice_buttons(self) -> None:
        self.mic_btn.setText("")
        self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
        self.sys_audio_btn.setText("")
        self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())

    def stop_voice_recording(self) -> None:
        """Safely terminate any active voice workers on shutdown or view change."""
        self._cancel_voice_recording()
