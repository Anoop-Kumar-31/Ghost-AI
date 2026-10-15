"""
Chat room view for Ghost AI.
Handles conversation display, streaming AI output, message formatting,
copying responses, and user input with keyboard shortcuts.
Strictly preserves the standard ArrowCursor across all elements.
"""

import re
from datetime import datetime
from typing import Optional, Dict, Any, List

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
    from pygments.formatters import HtmlFormatter
    from pygments.util import ClassNotFound
    _PYGMENTS = True
except ImportError:
    _PYGMENTS = False
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
)

from .config import load_config
from .ai_service import AIChatWorker
from .voice_worker import MicVoiceWorker, SysAudioWorker


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
        self.setPlaceholderText("Ask Ghost AI... (Enter to send, Shift+Enter for newline)")
        self.setFixedHeight(38)
        self.textChanged.connect(self._adjust_height)

        self.setStyleSheet(
            """
            QTextEdit {
                background-color: rgba(39, 39, 42, 0.85);
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 11px;
                font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QTextEdit:focus {
                border: 1px solid #3b82f6;
                background-color: rgba(39, 39, 42, 0.95);
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
                self.send_requested.emit()
                event.accept()
                return
        else:
            super().keyPressEvent(event)

    def _adjust_height(self) -> None:
        doc_height = int(self.document().size().height())
        new_height = max(38, min(120, doc_height + 12))
        self.setFixedHeight(new_height)


class MarkdownBrowser(QTextBrowser):
    """
    QTextBrowser for rendering Markdown content cleanly with stealth ArrowCursor
    and dynamic auto-height to prevent nested scrollbars.
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

        # Style sheet for typography & code blocks
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
        self.document().setDefaultStyleSheet(
            """
            code {
                background-color: rgba(255, 255, 255, 0.1);
                color: #93c5fd;
                border-radius: 3px;
                font-family: Consolas, "Courier New", monospace;
                padding: 1px 3px;
            }
            pre {
                background-color: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px;
                font-family: Consolas, "Courier New", monospace;
            }
            a {
                color: #60a5fa;
                text-decoration: underline;
            }
            ul, ol {
                margin-left: 14px;
                padding-left: 0px;
            }
            p {
                margin: 0px 0px 4px 0px;
                line-height: 1.4;
            }
            """
        )

        if content:
            self.set_content(content)

    # ------------------------------------------------------------------
    # Pygments-powered HTML renderer
    # ------------------------------------------------------------------
    _FENCED_RE = re.compile(
        r"```(?P<lang>[\w+-]*)\s*\n?(?P<code>.*?)```",
        re.DOTALL,
    )
    # VS Code Dark+ theme styles using Pygments one-dark
    _PYGMENTS_CSS = HtmlFormatter(style="one-dark").get_style_defs(".highlight") if _PYGMENTS else ""

    @classmethod
    def _highlight_code(cls, lang: str, code: str) -> str:
        """Return VS Code styled highlighted HTML snippet for a code block."""
        lang_str = lang.strip().lower() if lang else "code"
        if not _PYGMENTS:
            escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return (
                f'<div style="margin:6px 0; border:1px solid rgba(255,255,255,0.12); border-radius:6px; background:#1e1e1e; overflow:hidden;">'
                f'<div style="background:#252526; color:#858585; font-size:10px; font-weight:600; font-family:Consolas,monospace; padding:3px 8px; border-bottom:1px solid rgba(255,255,255,0.08);">{lang_str.upper()}</div>'
                f'<pre style="margin:0; padding:8px; font-family:Consolas,monospace; font-size:11px; color:#d4d4d4;"><code>{escaped}</code></pre>'
                f'</div>'
            )
        try:
            lexer = get_lexer_by_name(lang_str) if lang.strip() else guess_lexer(code)
        except ClassNotFound:
            lexer = TextLexer()
        formatter = HtmlFormatter(style="one-dark", nowrap=False, cssclass="highlight")
        highlighted = highlight(code, lexer, formatter)
        header_html = (
            f'<div style="background:#252526; color:#858585; font-size:10px; font-weight:600; font-family:Consolas,monospace; '
            f'padding:3px 8px; border-top-left-radius:6px; border-top-right-radius:6px; border-bottom:1px solid rgba(255,255,255,0.08); '
            f'letter-spacing:0.5px;">{lang_str.upper()}</div>'
        )
        return (
            f'<div style="margin:6px 0; border:1px solid rgba(255,255,255,0.12); border-radius:6px; background:#1e1e1e; overflow:hidden;">'
            f'{header_html}{highlighted}'
            f'</div>'
        )

    @classmethod
    def _markdown_to_html(cls, md: str) -> str:
        """Convert Markdown with fenced code blocks to HTML."""
        parts = []
        last = 0
        for m in cls._FENCED_RE.finditer(md):
            before = md[last:m.start()]
            parts.append(cls._markdown_prose_to_html(before))
            parts.append(cls._highlight_code(m.group("lang"), m.group("code")))
            last = m.end()
        parts.append(cls._markdown_prose_to_html(md[last:]))
        body = "".join(parts)
        css = cls._PYGMENTS_CSS
        return f"""<html><head><style>
{css}
body {{ color:#f4f4f5; font-family:'Segoe UI',Roboto,sans-serif; font-size:11px; text-align:left; }}
code {{ background:rgba(255,255,255,0.1); color:#93c5fd; border-radius:3px;
       font-family:Consolas,'Courier New',monospace; padding:1px 3px; }}
p {{ margin:0 0 4px 0; line-height:1.4; text-align:left; }}
ul,ol {{ margin-left:14px; padding-left:0; text-align:left; }}
a {{ color:#60a5fa; }}
.highlight {{ background:#1e1e1e !important; border:none; padding:6px 8px; margin:0; }}
.highlight pre {{ background:transparent !important; margin:0; padding:0;
                  font-family:'Cascadia Code',Consolas,'Courier New',monospace; font-size:11px; line-height:1.45; }}
</style></head><body>{body}</body></html>"""

    @staticmethod
    def _markdown_prose_to_html(text: str) -> str:
        """Minimal Markdown → HTML for prose sections (bold, italic, inline code, headers, lists)."""
        if not text:
            return ""
        # Escape raw HTML chars first
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = text.split("\n")
        html_lines = []
        in_ul = False
        for line in lines:
            stripped = line.rstrip()
            # Headers
            h = re.match(r'^(#{1,6})\s+(.*)', stripped)
            if h:
                if in_ul:
                    html_lines.append("</ul>"); in_ul = False
                lvl = len(h.group(1))
                html_lines.append(f"<h{lvl}>{_inline_md(h.group(2))}</h{lvl}>")
                continue
            # Unordered list
            li = re.match(r'^[\*\-\+]\s+(.*)', stripped)
            if li:
                if not in_ul:
                    html_lines.append("<ul>"); in_ul = True
                html_lines.append(f"<li>{_inline_md(li.group(1))}</li>")
                continue
            # Ordered list
            oli = re.match(r'^\d+\.\s+(.*)', stripped)
            if oli:
                if in_ul:
                    html_lines.append("</ul>"); in_ul = False
                html_lines.append(f"<li>{_inline_md(oli.group(1))}</li>")
                continue
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            # Blank line → paragraph break
            if stripped == "":
                html_lines.append("<p></p>")
            else:
                html_lines.append(f"<p>{_inline_md(stripped)}</p>")
        if in_ul:
            html_lines.append("</ul>")
        return "\n".join(html_lines)

    def set_content(self, md: str) -> None:
        """Render Markdown with highlighted code blocks as HTML."""
        html = self._markdown_to_html(md)
        self.setHtml(html)
        self.adjust_height()

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def setMarkdown(self, markdown: str) -> None:
        """Override to route through our HTML renderer."""
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


def _inline_md(text: str) -> str:
    """Apply inline Markdown: bold, italic, inline code."""
    # inline code  `...`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # bold  **...**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # italic  *...*
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    return text


class MessageBubble(QFrame):
    """Styled message bubble for User or AI with full Markdown support."""

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
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._init_ui(timestamp)

    def _init_ui(self, timestamp: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header: Role Badge + Copy Button
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        if self.role == "user":
            role_lbl = QLabel("You", self)
            role_lbl.setStyleSheet("color: #60a5fa; font-size: 10px; font-weight: 700;")
            self.setStyleSheet(
                """
                QFrame {
                    background-color: rgba(30, 58, 138, 0.35);
                    border: 1px solid rgba(59, 130, 246, 0.3);
                    border-radius: 8px;
                }
                """
            )
        else:
            role_lbl = QLabel("Ghost AI", self)
            role_lbl.setStyleSheet("color: #a1a1aa; font-size: 10px; font-weight: 700;")
            self.setStyleSheet(
                """
                QFrame {
                    background-color: rgba(39, 39, 42, 0.65);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 8px;
                }
                """
            )

        role_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        header.addWidget(role_lbl)
        header.addStretch()

        # Copy button
        copy_btn = QPushButton("Copy", self)
        copy_btn.setFixedSize(36, 18)
        copy_btn.setCursor(Qt.CursorShape.ArrowCursor)
        copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.06);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                font-size: 9px;
                padding: 1px 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }
            """
        )
        copy_btn.clicked.connect(self._copy_to_clipboard)
        header.addWidget(copy_btn)
        layout.addLayout(header)

        # Markdown Content Text Browser
        self.text_lbl = MarkdownBrowser(self.content, self)
        layout.addWidget(self.text_lbl)

    def update_content(self, text: str) -> None:
        """Update live streamed Markdown content."""
        self.content = text
        self.text_lbl.set_content(text)

    def _copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.content)



class ChatView(QWidget):
    """
    Active chat view container.
    Houses the top navigation bar, scrollable message list, and bottom prompt bar.
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

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # Home Button
        self.home_btn = QPushButton("⌂ Chats", self)
        self.home_btn.setFixedSize(62, 24)
        self.home_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.home_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.home_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(39, 39, 42, 0.8);
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 0.3);
                border: 1px solid #3b82f6;
            }
            """
        )
        self.home_btn.clicked.connect(self.home_requested.emit)
        header.addWidget(self.home_btn)

        # Chat Title (editable inline)
        self.title_edit = NoIBeamLineEdit(self)
        self.title_edit.setPlaceholderText("Untitled Chat")
        self.title_edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                border-bottom: 1px solid transparent;
                color: #f4f4f5;
                font-size: 12px;
                font-weight: 700;
                padding: 2px 4px;
            }
            QLineEdit:hover, QLineEdit:focus {
                border-bottom: 1px solid rgba(255, 255, 255, 0.2);
                background-color: rgba(255, 255, 255, 0.04);
                border-radius: 4px;
            }
            """
        )
        self.title_edit.editingFinished.connect(self._on_title_edited)
        header.addWidget(self.title_edit)

        # Quick New Chat button
        self.new_btn = QPushButton("+", self)
        self.new_btn.setFixedSize(24, 24)
        self.new_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.new_btn.setToolTip("New Chat (Ctrl+N)")
        self.new_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(39, 39, 42, 0.8);
                color: #f4f4f5;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
            }
            """
        )
        self.new_btn.clicked.connect(self.new_chat_requested.emit)
        header.addWidget(self.new_btn)

        # Settings gear button
        self.settings_btn = QPushButton("⚙", self)
        self.settings_btn.setFixedSize(24, 24)
        self.settings_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.settings_btn.setToolTip("Settings & API Key")
        self.settings_btn.setStyleSheet(
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
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        header.addWidget(self.settings_btn)

        # Spacer reserved for independent controls window (Blue & Red dots)
        header.addSpacing(42)
        main_layout.addLayout(header)

        # API Key Warning Banner (hidden when key is configured)
        self.banner = QFrame(self)
        self.banner.setObjectName("ApiKeyBanner")
        self.banner.setStyleSheet(
            """
            QFrame#ApiKeyBanner {
                background-color: rgba(180, 83, 9, 0.3);
                border: 1px solid rgba(245, 158, 11, 0.4);
                border-radius: 6px;
                padding: 4px;
            }
            """
        )
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        banner_lbl = QLabel("⚠️ API Key not configured. Click Settings to enter key.", self.banner)
        banner_lbl.setStyleSheet("color: #fcd34d; font-size: 10px; background: transparent;")
        banner_layout.addWidget(banner_lbl)
        banner_layout.addStretch()
        cfg_btn = QPushButton("Configure", self.banner)
        cfg_btn.setFixedSize(64, 20)
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

        # Scrollable Message Area
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

        self.messages_container = QWidget()
        self.messages_container.setCursor(Qt.CursorShape.ArrowCursor)
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(2, 4, 4, 4)
        self.messages_layout.setSpacing(8)
        self.messages_layout.addStretch()

        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, 1)

        # Voice Status Banner (shows live feedback when recording or transcribing)
        self.voice_status_frame = QFrame(self)
        self.voice_status_frame.setObjectName("VoiceStatusBanner")
        self.voice_status_frame.setStyleSheet(
            """
            QFrame#VoiceStatusBanner {
                background-color: rgba(24, 24, 27, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 2px 6px;
            }
            """
        )
        vs_layout = QHBoxLayout(self.voice_status_frame)
        vs_layout.setContentsMargins(8, 4, 8, 4)
        vs_layout.setSpacing(6)

        self.voice_status_lbl = QLabel(self.voice_status_frame)
        self.voice_status_lbl.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 500; background: transparent;")
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

        # Bottom Input Row
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)

        self.mic_btn = QPushButton("🎙️", self)
        self.mic_btn.setFixedSize(36, 36)
        self.mic_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.mic_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mic_btn.setToolTip("Record Microphone (Speech-to-Text)")
        self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
        self.mic_btn.clicked.connect(self._toggle_mic_recording)
        input_row.addWidget(self.mic_btn)

        self.sys_audio_btn = QPushButton("🔊", self)
        self.sys_audio_btn.setFixedSize(36, 36)
        self.sys_audio_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.sys_audio_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sys_audio_btn.setToolTip("Capture Meeting/System Audio (Google Meet / Zoom loopback)")
        self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())
        self.sys_audio_btn.clicked.connect(self._toggle_sys_audio_recording)
        input_row.addWidget(self.sys_audio_btn)

        self.input_edit = ChatInputEdit(self)
        self.input_edit.send_requested.connect(self._on_send_clicked)
        input_row.addWidget(self.input_edit, 1)

        self.send_btn = QPushButton("➤", self)
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.send_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.send_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.send_btn.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self.send_btn)

        main_layout.addLayout(input_row)

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

    def set_active_chat(self, chat: Dict[str, Any]) -> None:
        """Load and display the given chat session."""
        self._active_chat = chat
        self.title_edit.setText(chat.get("title", "Untitled Chat"))
        self._clear_messages_display()

        messages = chat.get("messages", [])
        if not messages:
            # Show friendly placeholder
            empty_lbl = QLabel(
                "💬 Start a conversation with Ghost AI.\n"
                "Responses are streaming, encrypted in transit, and completely invisible to screen capture.",
                self.messages_container,
            )
            empty_lbl.setObjectName("EmptyChatPlaceholder")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet("color: #71717a; font-size: 11px; padding: 30px 10px; background: transparent;")
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
            # Stop button action
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

        # Add user message
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

        # Start background worker
        cfg = load_config()
        self._current_worker = AIChatWorker(self._active_chat["messages"], cfg, self)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.finished.connect(self._on_generation_finished)
        self._current_worker.error.connect(self._on_generation_error)

        self._set_generating_state(True)
        self._current_worker.start()

    def _set_generating_state(self, generating: bool) -> None:
        if generating:
            self.send_btn.setText("⏹")
            self.send_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #dc2626;
                    color: #ffffff;
                    border: 1px solid #ef4444;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                }
                """
            )
        else:
            self.send_btn.setText("➤")
            self.send_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #2563eb;
                    color: #ffffff;
                    border: 1px solid #3b82f6;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1d4ed8;
                }
                """
            )

    def _on_chunk_received(self, chunk: str) -> None:
        if not self._streaming_bubble:
            return
        cur_text = self._streaming_bubble.content
        if cur_text == "...":
            new_text = chunk
        else:
            new_text = cur_text + chunk
        self._streaming_bubble.update_content(new_text)
        self._scroll_to_bottom()

    def _on_generation_finished(self, full_response: str) -> None:
        self._set_generating_state(False)
        if not self._active_chat or not self._streaming_bubble:
            return

        final_text = full_response if full_response else self._streaming_bubble.content
        if final_text == "...":
            final_text = "(Empty response)"
        self._streaming_bubble.update_content(final_text)

        now_iso = datetime.now().isoformat()
        ai_msg = {"role": "assistant", "content": final_text, "timestamp": now_iso}
        self._active_chat["messages"].append(ai_msg)
        self._active_chat["updated_at"] = now_iso
        self.chat_updated.emit()
        self._scroll_to_bottom()

    def _on_generation_error(self, err_msg: str) -> None:
        self._set_generating_state(False)
        if self._streaming_bubble:
            self._streaming_bubble.update_content(f"⚠️ {err_msg}")
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Voice-to-Text (Microphone & System/Meeting Audio WASAPI Loopback)
    # ------------------------------------------------------------------
    @staticmethod
    def _mic_btn_idle_style() -> str:
        return """
            QPushButton {
                background-color: rgba(39, 39, 42, 0.85);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
                border-color: rgba(255, 255, 255, 0.25);
            }
        """

    @staticmethod
    def _mic_btn_active_style() -> str:
        return """
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border: 1px solid #ef4444;
                border-radius: 8px;
                font-size: 14px;
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
                background-color: rgba(39, 39, 42, 0.85);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
                border-color: rgba(255, 255, 255, 0.25);
            }
        """

    @staticmethod
    def _sys_audio_btn_active_style() -> str:
        return """
            QPushButton {
                background-color: #7c3aed;
                color: #ffffff;
                border: 1px solid #8b5cf6;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
        """

    def _toggle_mic_recording(self) -> None:
        """Toggle microphone recording and transcription."""
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
        """Toggle system/meeting audio loopback recording and transcription."""
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
        self.mic_btn.setText("🎙️")
        self.mic_btn.setStyleSheet(self._mic_btn_idle_style())
        self.sys_audio_btn.setText("🔊")
        self.sys_audio_btn.setStyleSheet(self._sys_audio_btn_idle_style())

    def stop_voice_recording(self) -> None:
        """Safely terminate any active voice workers on shutdown or view change."""
        self._cancel_voice_recording()

