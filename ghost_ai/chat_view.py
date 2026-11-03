"""
Chat room view for Ghost AI.
Matches the sleek modern dark workspace UI:
- Large bold conversation title and "Your conversation workspace." subtitle.
- User and AI message bubbles with Markdown and Pygments syntax highlighting.
- Integrated prompt input card with:
    - "Ask anything..." multiline auto-expanding text editor.
    - Attachment button.
    - Microphone and system/meeting loopback audio buttons.
    - Green model selector pill (e.g. Claude, GPT-4o-mini).
    - Circular send button.
Strictly preserves the standard ArrowCursor across all elements.
"""
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
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
from .markdown_renderer import render_full_html, get_document_css
from .icon_manager import (
    get_icon,
    get_pixmap,
    IconButton,
    COLOR_DEFAULT,
    COLOR_ACTIVE,
    COLOR_HOVER,
)
ALLOWED_ATTACHMENT_EXTENSIONS = {".txt",".md",".py",".js",".ts",".jsx",".tsx",".json",".html",".css",".c",".cpp",".h",".hpp",".rs",".go",".java",".xml",".yaml",".yml",".toml",".sh",".bat",".ps1",".sql",".csv",
}
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
    """Auto-growing prompt field. Enter sends; Shift+Enter inserts a newline."""
    send_requested = Signal()
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatPromptEdit")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask anything...")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(36)
        self.setStyleSheet("""
            QTextEdit#ChatPromptEdit {
                background: transparent;
                color: #f4f4f5;
                border: none;
                padding: 3px 2px;
                font-size: 13px;
                selection-background-color: #514078;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QTextEdit#ChatPromptEdit::placeholder { color: #777987; }
        """)
        self.textChanged.connect(self._adjust_height)
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
        self.setFixedHeight(max(36, min(144, doc_height + 12)))
class MarkdownBrowser(QTextBrowser):
    """Document-style Markdown viewer using Ghost AI's shared Pygments renderer."""
    def __init__(self, content: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("AssistantMarkdown")
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet("""
            QTextBrowser#AssistantMarkdown {
                color: #e5e7eb;
                background: transparent;
                border: none;
                padding: 0;
                font-size: 13px;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
        """)
        self.document().setDefaultStyleSheet(get_document_css() + """
            body { color: #e5e7eb; font-family: "Segoe UI", sans-serif; font-size: 13px; }
            p { margin-top: 2px; margin-bottom: 10px; }
            h1, h2, h3, h4 { color: #f4f4f5; font-weight: 700; margin-top: 17px; margin-bottom: 8px; }
            h1 { font-size: 22px; } h2 { font-size: 18px; } h3 { font-size: 15px; }
            a { color: #b9a2ff; text-decoration: none; }
            blockquote { color: #b8bac6; border-left: 3px solid #8b5cf6; padding-left: 10px; }
            table { border-collapse: collapse; }
            th, td { border: 1px solid #343642; padding: 6px 9px; }
            th { background: #1b1d26; color: #f4f4f5; }
            hr { border: 0; border-top: 1px solid #30323b; }
        """)
        if content:
            self.set_content(content)
    def set_content(self, md: str) -> None:
        """Render source Markdown, never storing rendered HTML in chat history."""
        self.setHtml(render_full_html(md))
        self.adjust_height()
        QTimer.singleShot(0, self.adjust_height)
    def setMarkdown(self, markdown: str) -> None:
        self.set_content(markdown)
    def adjust_height(self) -> None:
        width = self.viewport().width()
        if width > 20:
            self.document().setTextWidth(width)
        height = int(self.document().documentLayout().documentSize().height())
        self.setFixedHeight(max(28, height + 8))
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
    """A compact user bubble or a clean, full-width assistant document."""
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
        self.setObjectName("UserMessageBubble" if role == "user" else "AssistantMessage")
        self._init_ui()
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(7)
        if self.role == "user":
            # Premium user prompt card with metadata and copy action.
            layout.setContentsMargins(14, 11, 14, 12)
            layout.setSpacing(9)
            # Header: sender + timestamp + copy action.
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(7)
            self.sender_lbl = QLabel("You", self)
            self.sender_lbl.setStyleSheet("""
                QLabel {
                    color: #c4b5fd;
                    background: transparent;
                    border: none;
                    font-size: 11px;
                    font-weight: 700;
                }
            """)
            header.addWidget(self.sender_lbl)
            header.addStretch(1)
            # Format the stored ISO timestamp.
            time_text = ""
            if self.timestamp:
                try:
                    time_text = datetime.fromisoformat(
                        self.timestamp
                    ).strftime("%I:%M %p").lstrip("0")
                except (ValueError, TypeError):
                    time_text = ""
            self.timestamp_lbl = QLabel(time_text, self)
            self.timestamp_lbl.setStyleSheet("""
                QLabel {
                    color: #858599;
                    background: transparent;
                    border: none;
                    font-size: 10px;
                }
            """)
            header.addWidget(self.timestamp_lbl)
            # Copy prompt button.
            self.copy_btn = QPushButton(self)
            self.copy_btn.setToolTip("Copy your prompt")
            self.copy_btn.setAccessibleName("Copy your prompt")
            self.copy_btn.setFixedSize(23, 23)
            self.copy_btn.setCursor(Qt.CursorShape.ArrowCursor)
            self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.copy_btn.setIcon(get_icon("copy", 12, "#9295a3"))
            self.copy_btn.setIconSize(QSize(12, 12))
            self.copy_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.08);
                    border-color: rgba(255, 255, 255, 0.10);
                }
            """)
            self.copy_btn.clicked.connect(self._copy_content)
            header.addWidget(self.copy_btn)
            layout.addLayout(header)
            # Actual user prompt.
            self.text_lbl = QLabel(self.content, self)
            self.text_lbl.setObjectName("UserMessageText")
            self.text_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self.text_lbl.setWordWrap(True)
            self.text_lbl.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.text_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.text_lbl.setCursor(Qt.CursorShape.ArrowCursor)
            self.text_lbl.setStyleSheet("""
                QLabel#UserMessageText {
                    color: #f4f1ff;
                    background: transparent;
                    border: none;
                    padding: 0;
                    font-size: 13px;
                    font-weight: 450;
                    selection-background-color: #66518f;
                    font-family: "Segoe UI", Arial, sans-serif;
                }
            """)
            layout.addWidget(self.text_lbl)
            self.setMinimumWidth(280)
            self.setMaximumWidth(760)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred
            )
            self.setAttribute(
                Qt.WidgetAttribute.WA_StyledBackground, True
            )
            self.setStyleSheet("""
                QFrame#UserMessageBubble {
                    background: qlineargradient(
                        x1: 0, y1: 0, x2: 1, y2: 1,
                        stop: 0 #302743,
                        stop: 1 #211d2e
                    );
                    border: 1px solid rgba(167, 139, 250, 0.24);
                    border-radius: 15px;
                }
                QFrame#UserMessageBubble:hover {
                    border: 1px solid rgba(167, 139, 250, 0.48);
                    background-color: #302743;
                }
            """)
            return
        layout.setContentsMargins(0, 2, 0, 8)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)
        self.avatar_lbl = QLabel("✦", self)
        self.avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_lbl.setFixedSize(27, 27)
        self.avatar_lbl.setStyleSheet("""
            QLabel { color: #c4b5fd; background: #28213d; border: 1px solid #3b3158;
                border-radius: 8px; font-size: 17px; font-weight: 700; }
        """)
        header.addWidget(self.avatar_lbl)
        self.sender_lbl = QLabel("Ghost AI", self)
        self.sender_lbl.setStyleSheet("""
            QLabel { color: #f4f4f5; background: transparent; border: none;
                font-size: 13px; font-weight: 700; }
        """)
        header.addWidget(self.sender_lbl)
        header.addStretch(1)
        self.copy_btn = QPushButton(self)
        self.copy_btn.setToolTip("Copy response")
        self.copy_btn.setAccessibleName("Copy response")
        self.copy_btn.setFixedSize(25, 25)
        self.copy_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.setIcon(get_icon("copy", 14, "#9295a3"))
        self.copy_btn.setIconSize(QSize(14, 14))
        self.copy_btn.setStyleSheet("""
            QPushButton { background: transparent; border: 1px solid transparent; border-radius: 6px; }
            QPushButton:hover { background: #20212a; border-color: #343642; }
        """)
        self.copy_btn.clicked.connect(self._copy_content)
        header.addWidget(self.copy_btn)
        layout.addLayout(header)
        self.text_lbl = MarkdownBrowser(self.content, self)
        layout.addWidget(self.text_lbl)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("QFrame#AssistantMessage { background: transparent; border: none; }")
    def _update_message_widths(self):
        available_width = self.scroll_area.viewport().width()
        max_width = max(280, int(available_width * 0.72))
        for bubble in self.messages_container.findChildren(MessageBubble):
            if bubble.role == "user":
                bubble.setMaximumWidth(max_width)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_message_widths)
    def update_content(self, text: str) -> None:
        """Update the live streamed Markdown body."""
        self.content = text
        if self.role == "user":
            if isinstance(self.text_lbl, QLabel):
                self.text_lbl.setText(text)
        elif isinstance(self.text_lbl, MarkdownBrowser):
            self.text_lbl.set_content(text)
    
    def _copy_content(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self.content)
        self.copy_btn.setIcon(
            get_icon("circle-check", 14, "#34d399")
        )
        QTimer.singleShot(
            1400,
            lambda: (
                self.copy_btn.setIcon(
                    get_icon("copy", 12 if self.role == "user" else 14, "#9295a3")
                )
                if self.copy_btn is not None
                else None
            ),
        )
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
                    self._generation_contexts: Dict[str, Dict[str, Any]] = {}
                    self._streaming_bubble: Optional[MessageBubble] = None
                    self._mic_worker: Optional[MicVoiceWorker] = None
                    self._sys_worker: Optional[SysAudioWorker] = None
                    # Streaming render debounce (75ms)
                    self._streaming_buffer: str = ""
                    self._stream_timer = QTimer(self)
                    self._stream_timer.setInterval(75)
                    self._stream_timer.setSingleShot(True)
                    self._stream_timer.timeout.connect(self._flush_stream_buffer)
                    self._init_ui()
          def _init_ui(self) -> None:
              self.setObjectName("ChatView")
              self.setStyleSheet("QWidget#ChatView { background: #0d0e13; color: #f4f4f5; }")
              main_layout = QVBoxLayout(self)
              main_layout.setContentsMargins(6, 0, 6, 7)
              main_layout.setSpacing(8)
              # Conversation title, subtitle and compact options button.
              header_top = QHBoxLayout()
              header_top.setContentsMargins(0, 7, 0, 0)
              header_top.setSpacing(8)
              title_stack = QVBoxLayout()
              title_stack.setContentsMargins(0, 0, 0, 0)
              title_stack.setSpacing(1)
              self.title_edit = NoIBeamLineEdit(self)
              self.title_edit.setPlaceholderText("Untitled Chat")
              self.title_edit.setMinimumHeight(24)
              self.title_edit.setStyleSheet("""
                  QLineEdit {
                      background: transparent; border: none; color: #f4f4f5;
                      font-size: 17px; font-weight: 700; padding: 0;
                      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
                  }
                  QLineEdit:hover, QLineEdit:focus { color: #ffffff; }
              """)
              self.title_edit.editingFinished.connect(self._on_title_edited)
              title_stack.addWidget(self.title_edit)
              self.subtitle_lbl = QLabel("Your conversation workspace", self)
              self.subtitle_lbl.setStyleSheet("color: #858896; font-size: 10px; background: transparent;")
              title_stack.addWidget(self.subtitle_lbl)
              header_top.addLayout(title_stack, 1)
              self.header_more_btn = QPushButton("•••", self)
              self.header_more_btn.setToolTip("Settings and options")
              self.header_more_btn.setFixedSize(30, 28)
              self.header_more_btn.setCursor(Qt.CursorShape.ArrowCursor)
              self.header_more_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.header_more_btn.setStyleSheet("""
                  QPushButton { color: #858896; background: transparent; border: none;
                      border-radius: 7px; font-size: 12px; font-weight: 700; }
                  QPushButton:hover { color: #f4f4f5; background: #1b1c24; }
              """)
              self.header_more_btn.clicked.connect(self.settings_requested.emit)
              header_top.addWidget(self.header_more_btn, 0, Qt.AlignmentFlag.AlignTop)
              main_layout.addLayout(header_top)
              self.header_divider = QFrame(self)
              self.header_divider.setFixedHeight(1)
              self.header_divider.setStyleSheet("background: #292b34; border: none;")
              main_layout.addWidget(self.header_divider)
              # Compatibility buttons retained for the existing main window and tests.
              self.home_btn = QPushButton("⌂ Chats", self)
              self.home_btn.hide()
              self.home_btn.clicked.connect(self.home_requested.emit)
              self.new_btn = QPushButton("+", self)
              self.new_btn.hide()
              self.new_btn.clicked.connect(self.new_chat_requested.emit)
              self.settings_btn = QPushButton("⚙", self)
              self.settings_btn.hide()
              self.settings_btn.clicked.connect(self.settings_requested.emit)
              # API-key banner.
              self.banner = QFrame(self)
              self.banner.setObjectName("ApiKeyBanner")
              self.banner.setStyleSheet("""
                  QFrame#ApiKeyBanner {
                      background: #2a2115; border: 1px solid #594321;
                      border-radius: 9px; padding: 3px;
                  }
              """)
              banner_layout = QHBoxLayout(self.banner)
              banner_layout.setContentsMargins(11, 6, 10, 6)
              banner_lbl = QLabel("API key not configured. Add one in Settings to start chatting.", self.banner)
              banner_lbl.setStyleSheet("color: #f4cc83; font-size: 11px; background: transparent;")
              banner_layout.addWidget(banner_lbl, 1)
              cfg_btn = QPushButton("Configure", self.banner)
              cfg_btn.setFixedSize(76, 25)
              cfg_btn.setCursor(Qt.CursorShape.ArrowCursor)
              cfg_btn.setStyleSheet("""
                  QPushButton { color: #fff7ed; background: #a65f12; border: none;
                      border-radius: 6px; font-size: 10px; font-weight: 650; }
                  QPushButton:hover { background: #bd701b; }
              """)
              cfg_btn.clicked.connect(self.settings_requested.emit)
              banner_layout.addWidget(cfg_btn)
              main_layout.addWidget(self.banner)
              # Conversation transcript.
              self.scroll_area = QScrollArea(self)
              self.scroll_area.setWidgetResizable(True)
              self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
              self.scroll_area.setCursor(Qt.CursorShape.ArrowCursor)
              self.scroll_area.viewport().setCursor(Qt.CursorShape.ArrowCursor)
              self.scroll_area.setStyleSheet("""
                  QScrollArea { background: transparent; border: none; }
                  QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
                  QScrollBar::handle:vertical { background: #343640; min-height: 24px; border-radius: 3px; }
                  QScrollBar::handle:vertical:hover { background: #4a4c58; }
                  QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
              """)
              self.messages_container = QWidget()
              self.messages_container.setCursor(Qt.CursorShape.ArrowCursor)
              self.messages_container.setStyleSheet("background: transparent;")
              self.messages_layout = QVBoxLayout(self.messages_container)
              self.messages_layout.setContentsMargins(0, 13, 0, 12)
              self.messages_layout.setSpacing(17)
              self.messages_layout.addStretch(1)
              self.scroll_area.setWidget(self.messages_container)
              main_layout.addWidget(self.scroll_area, 1)
              # Voice/transcription status banner.
              self.voice_status_frame = QFrame(self)
              self.voice_status_frame.setObjectName("VoiceStatusBanner")
              self.voice_status_frame.setStyleSheet("""
                  QFrame#VoiceStatusBanner { background: #191827; border: 1px solid #393151;
                      border-radius: 9px; padding: 2px 5px; }
              """)
              vs_layout = QHBoxLayout(self.voice_status_frame)
              vs_layout.setContentsMargins(10, 5, 8, 5)
              vs_layout.setSpacing(5)
              self.voice_status_lbl = QLabel(self.voice_status_frame)
              self.voice_status_lbl.setStyleSheet("color: #c4b5fd; font-size: 11px; background: transparent;")
              vs_layout.addWidget(self.voice_status_lbl, 1)
              self.voice_cancel_btn = QPushButton("×", self.voice_status_frame)
              self.voice_cancel_btn.setFixedSize(20, 20)
              self.voice_cancel_btn.setCursor(Qt.CursorShape.ArrowCursor)
              self.voice_cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.voice_cancel_btn.setStyleSheet("QPushButton { color: #a1a1aa; background: transparent; border: none; font-size: 16px; } QPushButton:hover { color: white; }")
              self.voice_cancel_btn.clicked.connect(self._cancel_voice_recording)
              vs_layout.addWidget(self.voice_cancel_btn)
              self.voice_status_frame.hide()
              main_layout.addWidget(self.voice_status_frame)
              # Composer: input surface + tool row.
              self.input_card = QFrame(self)
              self.input_card.setObjectName("ChatInputCard")
              self.input_card.setCursor(Qt.CursorShape.ArrowCursor)
              self.input_card.setStyleSheet("""
                  QFrame#ChatInputCard {
                      background: #171820;
                      border: 1px solid #353743;
                      border-radius: 16px;
                  }
              """)
              card_layout = QVBoxLayout(self.input_card)
              card_layout.setContentsMargins(10, 8, 9, 8)
              card_layout.setSpacing(6)
              self.input_edit = ChatInputEdit(self.input_card)
              self.input_edit.send_requested.connect(self._on_send_clicked)
              card_layout.addWidget(self.input_edit)
              bottom_row = QHBoxLayout()
              bottom_row.setContentsMargins(0, 0, 0, 0)
              bottom_row.setSpacing(3)
              self.attach_btn = IconButton(
                  "paperclip", size=16, btn_size=28,
                  color_default=COLOR_DEFAULT, color_hover=COLOR_HOVER,
                  parent=self.input_card,
              )
              self.attach_btn.setToolTip("Attach a text or code file")
              self.attach_btn.clicked.connect(self._on_attach_clicked)
              bottom_row.addWidget(self.attach_btn)
              self.mic_btn = QPushButton(self.input_card)
              self.mic_btn.setFixedSize(28, 28)
              self.mic_btn.setCursor(Qt.CursorShape.ArrowCursor)
              self.mic_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.mic_btn.setToolTip("Transcribe microphone audio")
              self.mic_btn.setIcon(get_icon("mic", 16, COLOR_DEFAULT))
              self.mic_btn.setIconSize(QSize(16, 16))
              self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
              self.mic_btn.clicked.connect(self._toggle_mic_recording)
              bottom_row.addWidget(self.mic_btn)
              self.sys_audio_btn = QPushButton(self.input_card)
              self.sys_audio_btn.setFixedSize(28, 28)
              self.sys_audio_btn.setCursor(Qt.CursorShape.ArrowCursor)
              self.sys_audio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.sys_audio_btn.setToolTip("Transcribe system / meeting audio")
              self.sys_audio_btn.setIcon(get_icon("volume-2", 16, COLOR_DEFAULT))
              self.sys_audio_btn.setIconSize(QSize(16, 16))
              self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())
              self.sys_audio_btn.clicked.connect(self._toggle_sys_audio_recording)
              bottom_row.addWidget(self.sys_audio_btn)
              bottom_row.addStretch(1)
              self.model_badge = QPushButton("Claude", self.input_card)
              self.model_badge.setCursor(Qt.CursorShape.ArrowCursor)
              self.model_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.model_badge.setToolTip("Change model or provider in Settings")
              self.model_badge.setStyleSheet("""
                  QPushButton { color: #22c983; background: rgba(16, 185, 129, 0.10);
                      border: 1px solid rgba(16, 185, 129, 0.22); border-radius: 10px;
                      padding: 3px 9px; font-size: 10px; font-weight: 700; }
                  QPushButton:hover { background: rgba(16, 185, 129, 0.17); border-color: rgba(16, 185, 129, 0.38); }
              """)
              self.model_badge.clicked.connect(self.settings_requested.emit)
              bottom_row.addWidget(self.model_badge)
              self.send_btn = QPushButton(self.input_card)
              self.send_btn.setFixedSize(32, 32)
              self.send_btn.setCursor(Qt.CursorShape.ArrowCursor)
              self.send_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
              self.send_btn.setToolTip("Send message")
              self.send_btn.setIcon(get_icon("arrow-up", 16, "#ffffff"))
              self.send_btn.setIconSize(QSize(16, 16))
              self.send_btn.setStyleSheet("""
                  QPushButton { background: #8b5cf6; border: 1px solid #a78bfa; border-radius: 10px; }
                  QPushButton:hover { background: #9b72fa; }
                  QPushButton:pressed { background: #7544dc; }
              """)
              self.send_btn.clicked.connect(self._on_send_clicked)
              bottom_row.addWidget(self.send_btn)
              card_layout.addLayout(bottom_row)
              main_layout.addWidget(self.input_card)
              self.check_api_key_banner()
              self._update_model_badge()
          def _update_model_badge(self) -> None:
                    """Update model pill text based on current configuration."""
                    if not hasattr(self, "model_badge") or self.model_badge is None:
                              return
                    cfg = load_config()
                    model_name = str(cfg.get("model", "Claude") or "Claude")
                    lower_name = model_name.lower()
                    if "claude" in lower_name:
                              display = "Claude"
                    elif "gpt-4o-mini" in lower_name:
                              display = "GPT-4o-mini"
                    elif "gpt-4o" in lower_name:
                              display = "GPT-4o"
                    elif "deepseek" in lower_name:
                              display = "DeepSeek"
                    elif "llama" in lower_name:
                              display = "Llama"
                    elif "gemini" in lower_name:
                              display = "Gemini"
                    else:
                              display = model_name.split("/")[-1].split(":")[0]
                              if len(display) > 16:
                                        display = display[:14] + "…"
                    self.model_badge.setText(display)
          def _on_attach_clicked(self) -> None:
                    """Open file dialog to attach text or code file into prompt."""
                    path, _ = QFileDialog.getOpenFileName(
                              self, "Attach file", "", "Code & Text files (*.txt *.md *.py *.js *.ts *.jsx *.tsx *.json *.html *.css *.c *.cpp *.h *.rs *.go *.java *.xml *.yaml *.yml *.toml *.sh *.bat *.ps1 *.sql *.csv);;All files (*.*)"
                    )
                    if not path:
                              return
                    file_path = Path(path)
                    if file_path.suffix.lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
                              self.voice_status_lbl.setText(f"⚠️ Unsupported file type: {file_path.suffix}")
                              self.voice_status_frame.show()
                              QTimer.singleShot(3500, self.voice_status_frame.hide)
                              return
                    try:
                              # 1 MB size guard to avoid locking UI
                              if file_path.stat().st_size > 1024 * 1024:
                                        self.voice_status_lbl.setText(f"⚠️ File too large (> 1MB): {file_path.name}")
                                        self.voice_status_frame.show()
                                        QTimer.singleShot(3500, self.voice_status_frame.hide)
                                        return
                              with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                                        content = f.read(10001)
                              truncated = len(content) > 10000
                              content = content[:10000]
                              trunc_note = "\n[Content truncated to 10,000 characters]" if truncated else ""
                              prefix = f"--- Context from {file_path.name} ---\n{content}{trunc_note}\n---\n"
                              cur = self.input_edit.toPlainText().strip()
                              self.input_edit.setPlainText(f"{prefix}\n{cur}" if cur else prefix)
                              self.input_edit.setFocus()
                    except Exception:
                              self.voice_status_lbl.setText(f"⚠️ Could not read file: {file_path.name}")
                              self.voice_status_frame.show()
                              QTimer.singleShot(3500, self.voice_status_frame.hide)
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
          def _get_generation_for_chat(self, chat_id: Optional[str]) -> Optional[Dict[str, Any]]:
                    """Find active generation context for a given chat ID."""
                    if not chat_id:
                              return None
                    for ctx in self._generation_contexts.values():
                              if ctx.get("chat_id") == chat_id:
                                        return ctx
                    return None
          def _refresh_active_generation_state(self) -> None:
                    """Synchronize current worker reference and send button style with active chat."""
                    if not self._active_chat:
                              self._current_worker = None
                              self._set_generating_state(False)
                              return
                    chat_id = self._active_chat.get("id")
                    active_ctx = self._get_generation_for_chat(chat_id)
                    if active_ctx:
                              self._current_worker = active_ctx.get("worker")
                              self._set_generating_state(True)
                    else:
                              self._current_worker = None
                              self._set_generating_state(False)
          def cancel_generations_for_chat(self, chat_id: str) -> None:
                    """Cancel any running generation worker associated with chat_id."""
                    for req_id, ctx in list(self._generation_contexts.items()):
                              if ctx.get("chat_id") == chat_id:
                                        worker = ctx.get("worker")
                                        if worker:
                                                  worker.cancel()
                    if self._active_chat and self._active_chat.get("id") == chat_id:
                              self._refresh_active_generation_state()
          def set_active_chat(self, chat: Dict[str, Any]) -> None:
                    """Load and display the given chat session."""
                    self._active_chat = chat
                    title = chat.get("title", "Untitled Chat")
                    self.title_edit.setText(title)
                    self._clear_messages_display()
                    messages = chat.get("messages", [])
                    chat_id = chat.get("id", "")
                    active_ctx = self._get_generation_for_chat(chat_id)
                    self._refresh_active_generation_state()
                    if not messages and not active_ctx:
                              empty_lbl = QLabel(
                                        "Start a conversation with Ghost AI\n\nAsk a question, explore an idea, or paste code to get started.",
                                        self.messages_container,
                              )
                              empty_lbl.setObjectName("EmptyChatPlaceholder")
                              empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                              empty_lbl.setWordWrap(True)
                              empty_lbl.setStyleSheet(
                                        "color: #858896; font-size: 13px; line-height: 1.5; padding: 42px 18px; background: transparent;"
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
                              # Re-attach streaming bubble if this chat has active generation
                              if active_ctx:
                                        disp_text = active_ctx.get("buffer") or "..."
                                        bubble = MessageBubble("assistant", disp_text, datetime.now().isoformat(), self.messages_container)
                                        active_ctx["bubble"] = bubble
                                        self._add_bubble_row(bubble)
                    if active_ctx and active_ctx.get("pending_render"):
                              self._stream_timer.start()
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
            row = QWidget(self.messages_container)
            row.setCursor(Qt.CursorShape.ArrowCursor)
            row.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)
            if bubble.role == "user":
                bubble.setMaximumWidth(
                    max(280, int(self.scroll_area.viewport().width() * 0.72))
                )
                row_layout.addStretch(1)
                row_layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
            else:
                row_layout.addWidget(bubble, 1)
                row_layout.addStretch(0)
            self.messages_layout.insertWidget(
                self.messages_layout.count() - 1,
                row
            )
          def resizeEvent(self, event) -> None:
                    super().resizeEvent(event)
                    if not hasattr(self, "messages_container"):
                              return
                    available_width = max(1, self.scroll_area.viewport().width())
                    for row in self.messages_container.findChildren(QWidget):
                              bubble = row.findChild(MessageBubble)
                              if bubble and bubble.role == "user":
                                        bubble.setMaximumWidth(max(160, int(available_width * 0.68)))
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
                    bubble = MessageBubble("assistant", "...", now_iso, self.messages_container)
                    self._add_bubble_row(bubble)
                    self._scroll_to_bottom()
                    chat = self._active_chat
                    chat_id = chat.get("id", "")
                    request_id = str(uuid.uuid4())
                    messages_snapshot = [dict(m) for m in chat.get("messages", [])]
                    cfg = load_config()
                    worker = AIChatWorker(messages_snapshot, cfg, self, request_id=request_id)
                    self._current_worker = worker
                    self._generation_contexts[request_id] = {
                              "chat_id": chat_id,
                              "chat": chat,
                              "bubble": bubble,
                              "buffer": "",
                              "worker": worker,
                    }
                    worker.chunk_received.connect(self._on_worker_chunk)
                    worker.response_finished.connect(self._on_worker_finished)
                    worker.cancelled.connect(self._on_worker_cancelled)
                    worker.error.connect(self._on_worker_error)
                    self._refresh_active_generation_state()
                    worker.start()
          def _set_generating_state(self, generating: bool) -> None:
                    if generating:
                              self.send_btn.setIcon(get_icon("square", 12, "#ffffff"))
                              self.send_btn.setStyleSheet(
                                        """
                                        QPushButton {
                                                  background-color: #dc2626;
                                                  border: 1px solid #ef4444;
                                                  border-radius: 8px;
                                        }
                                        QPushButton:hover {
                                                  background-color: #b91c1c;
                                        }
                                        QPushButton:pressed {
                                                  background-color: #991b1b;
                                        }
                                        """
                              )
                    else:
                              self.send_btn.setIcon(get_icon("arrow-up", 16, "#ffffff"))
                              self.send_btn.setStyleSheet(
                                        """
                                        QPushButton {
                                                  background-color: #8b5cf6;
                                                  border: 1px solid rgba(185, 154, 255, 0.25);
                                                  border-radius: 8px;
                                        }
                                        QPushButton:hover {
                                                  background-color: #9d75ff;
                                                  border-color: #b99aff;
                                        }
                                        QPushButton:pressed {
                                                  background-color: #7c3aed;
                                        }
                                        """
                              )
          def _on_worker_chunk(self, request_id: str, chunk: str) -> None:
                    context = self._generation_contexts.get(request_id)
                    if not context:
                              return
                    if context["buffer"] == "...":
                              context["buffer"] = chunk
                    else:
                              context["buffer"] += chunk
                    context["pending_render"] = True
                    if self._active_chat and self._active_chat.get("id") == context["chat_id"]:
                              if not self._stream_timer.isActive():
                                        self._stream_timer.start()
          def _flush_stream_buffer(self) -> None:
                    if not self._active_chat:
                              return
                    active_id = self._active_chat.get("id")
                    for ctx in self._generation_contexts.values():
                              if ctx.get("chat_id") == active_id and ctx.get("pending_render"):
                                        bubble = ctx.get("bubble")
                                        if bubble:
                                                  bubble.update_content(ctx["buffer"])
                                                  self._scroll_to_bottom()
                                        ctx["pending_render"] = False
                    has_visible_pending = any(
                              ctx.get("chat_id") == active_id and ctx.get("pending_render")
                              for ctx in self._generation_contexts.values()
                    )
                    if has_visible_pending:
                              self._stream_timer.start()
                    else:
                              self._stream_timer.stop()
          def _on_worker_finished(self, request_id: str, full_response: str) -> None:
                    context = self._generation_contexts.pop(request_id, None)
                    if not context:
                              return
                    final_text = full_response if full_response else context.get("buffer", "")
                    if not final_text or final_text == "...":
                              final_text = "(Empty response)"
                    now_iso = datetime.now().isoformat()
                    target_chat = context.get("chat")
                    if target_chat is not None:
                              ai_msg = {"role": "assistant", "content": final_text, "timestamp": now_iso}
                              if "messages" not in target_chat:
                                        target_chat["messages"] = []
                              target_chat["messages"].append(ai_msg)
                              target_chat["updated_at"] = now_iso
                              self.chat_updated.emit()
                    if self._active_chat and self._active_chat.get("id") == context.get("chat_id"):
                              bubble = context.get("bubble")
                              if bubble:
                                        bubble.update_content(final_text)
                                        self._scroll_to_bottom()
                              self._refresh_active_generation_state()
                    if not any(ctx.get("pending_render") for ctx in self._generation_contexts.values()):
                              self._stream_timer.stop()
          def _on_worker_cancelled(self, request_id: str, partial_response: str) -> None:
                    context = self._generation_contexts.pop(request_id, None)
                    if not context:
                              return
                    final_text = partial_response if partial_response else context.get("buffer", "")
                    target_chat = context.get("chat")
                    now_iso = datetime.now().isoformat()
                    if target_chat is not None and final_text and final_text != "...":
                              ai_msg = {
                                        "role": "assistant",
                                        "content": final_text,
                                        "timestamp": now_iso,
                                        "interrupted": True,
                              }
                              if "messages" not in target_chat:
                                        target_chat["messages"] = []
                              target_chat["messages"].append(ai_msg)
                              target_chat["updated_at"] = now_iso
                              self.chat_updated.emit()
                    if self._active_chat and self._active_chat.get("id") == context.get("chat_id"):
                              bubble = context.get("bubble")
                              if bubble:
                                        disp = final_text if (final_text and final_text != "...") else "(Cancelled)"
                                        bubble.update_content(f"{disp}\n\n*[Response cancelled]*")
                                        self._scroll_to_bottom()
                              self._refresh_active_generation_state()
                    if not any(ctx.get("pending_render") for ctx in self._generation_contexts.values()):
                              self._stream_timer.stop()
          def _on_worker_error(self, request_id: str, err_msg: str) -> None:
                    context = self._generation_contexts.pop(request_id, None)
                    if not context:
                              return
                    if self._active_chat and self._active_chat.get("id") == context.get("chat_id"):
                              bubble = context.get("bubble")
                              if bubble:
                                        bubble.update_content(f"⚠️ {err_msg}")
                                        self._scroll_to_bottom()
                              self._refresh_active_generation_state()
                    if not any(ctx.get("pending_render") for ctx in self._generation_contexts.values()):
                              self._stream_timer.stop()
          def has_active_workers(self) -> bool:
                    """Check if any AI or voice background workers are currently running."""
                    ai_active = any(
                              ctx.get("worker") and ctx["worker"].isRunning()
                              for ctx in self._generation_contexts.values()
                    )
                    if self._current_worker and self._current_worker.isRunning():
                              ai_active = True
                    mic_active = self._mic_worker is not None and self._mic_worker.isRunning()
                    sys_active = self._sys_worker is not None and self._sys_worker.isRunning()
                    return ai_active or mic_active or sys_active
          def cancel_all_workers(self) -> None:
                    """Request non-blocking cooperative cancellation on all active workers."""
                    self._stream_timer.stop()
                    for ctx in list(self._generation_contexts.values()):
                              w = ctx.get("worker")
                              if w and w.isRunning():
                                        w.cancel()
                    if self._current_worker and self._current_worker.isRunning():
                              self._current_worker.cancel()
                    if self._mic_worker and self._mic_worker.isRunning():
                              self._mic_worker.cancel()
                    if self._sys_worker and self._sys_worker.isRunning():
                              self._sys_worker.cancel()
          def shutdown_workers(self, timeout_ms: int = 5000) -> bool:
                    """Safely terminate any active AI workers and voice recording on shutdown."""
                    self.cancel_all_workers()
                    clean = True
                    per_worker_timeout = max(500, timeout_ms // max(1, len(self._generation_contexts) + 2))
                    for ctx in list(self._generation_contexts.values()):
                              w = ctx.get("worker")
                              if w and w.isRunning():
                                        if not w.wait(per_worker_timeout):
                                                  clean = False
                    if self._mic_worker and self._mic_worker.isRunning():
                              if not self._mic_worker.wait(1000):
                                        clean = False
                    if self._sys_worker and self._sys_worker.isRunning():
                              if not self._sys_worker.wait(1000):
                                        clean = False
                    return clean
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
          def _cancel_voice_recording(self, timeout_ms: int = 1500) -> bool:
                    clean = True
                    if self._mic_worker and self._mic_worker.isRunning():
                              self._mic_worker.cancel()
                              if not self._mic_worker.wait(timeout_ms):
                                        clean = False
                    if self._sys_worker and self._sys_worker.isRunning():
                              self._sys_worker.cancel()
                              if not self._sys_worker.wait(timeout_ms):
                                        clean = False
                    self._reset_voice_buttons()
                    self.voice_status_frame.hide()
                    return clean
          def _reset_voice_buttons(self) -> None:
                    self.mic_btn.setText("")
                    self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
                    self.sys_audio_btn.setText("")
                    self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())
          def stop_voice_recording(self, timeout_ms: int = 1500) -> bool:
                    """Safely terminate any active voice workers on shutdown or view change."""
                    return self._cancel_voice_recording(timeout_ms=timeout_ms)
