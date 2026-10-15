"""
Centralized Markdown renderer for Ghost AI.
Uses markdown-it-py (CommonMark + GFM tables) for safe document parsing and
Pygments for language-aware code syntax highlighting in VS Code Dark+ styling.
"""

from __future__ import annotations

import logging
from typing import Optional

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

logger = logging.getLogger(__name__)

# Base Pygments syntax highlighting CSS (VS Code Dark+ / One-Dark palette)
_PYGMENTS_STYLE = "one-dark"
_PYGMENTS_CSS = HtmlFormatter(style=_PYGMENTS_STYLE).get_style_defs(".highlight")


def highlight_code(code: str, lang: str = "") -> str:
    """
    Syntax-highlight code using Pygments.
    Falls back gracefully to plain text for unknown language tags.
    """
    lang_clean = lang.strip().lower() if lang else ""
    # Map common aliases if needed
    if lang_clean in ("js", "javascript"):
        lexer_name = "javascript"
    elif lang_clean in ("ts", "typescript"):
        lexer_name = "typescript"
    elif lang_clean in ("jsx", "tsx"):
        lexer_name = "jsx" if lang_clean == "jsx" else "typescript"
    elif lang_clean in ("py", "python"):
        lexer_name = "python"
    elif lang_clean in ("sh", "shell", "bash"):
        lexer_name = "bash"
    elif lang_clean:
        lexer_name = lang_clean
    else:
        lexer_name = ""

    try:
        lexer = get_lexer_by_name(lexer_name) if lexer_name else guess_lexer(code)
    except (ClassNotFound, Exception):
        lexer = TextLexer()

    formatter = HtmlFormatter(style=_PYGMENTS_STYLE, nowrap=False, cssclass="highlight")
    return highlight(code, lexer, formatter)


def _render_fence(self, tokens, idx, options, env):
    """Custom fence render rule for markdown-it-py."""
    token = tokens[idx]
    lang = token.info.strip().lower() if token.info else ""
    code = token.content
    highlighted = highlight_code(code, lang)
    lang_display = lang.upper() if lang else "CODE"

    return (
        f'<table class="code-block-box" width="100%" cellpadding="0" cellspacing="0" bgcolor="#0d0d0d">\n'
        f'<tr><td class="code-header" bgcolor="#1e1e1e">{lang_display}</td></tr>\n'
        f'<tr><td class="code-body" bgcolor="#0d0d0d">{highlighted}</td></tr>\n'
        f'</table>\n'
    )


def _render_code_block(self, tokens, idx, options, env):
    """Custom indented code block rule for markdown-it-py."""
    token = tokens[idx]
    code = token.content
    highlighted = highlight_code(code, "")
    return (
        f'<table class="code-block-box" width="100%" cellpadding="0" cellspacing="0" bgcolor="#0d0d0d">\n'
        f'<tr><td class="code-header" bgcolor="#1e1e1e">CODE</td></tr>\n'
        f'<tr><td class="code-body" bgcolor="#0d0d0d">{highlighted}</td></tr>\n'
        f'</table>\n'
    )


def _create_markdown_parser() -> MarkdownIt:
    """Instantiate and configure markdown-it-py parser."""
    md = MarkdownIt("js-default", {"html": False, "linkify": False})
    md.add_render_rule("fence", _render_fence)
    md.add_render_rule("code_block", _render_code_block)
    return md


# Thread-safe global parser instance
_MD_PARSER = _create_markdown_parser()


def get_document_css() -> str:
    """Return styling CSS compatible with QTextBrowser."""
    return f"""
{_PYGMENTS_CSS}
body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 11px;
    text-align: left;
    margin: 0;
    padding: 0;
}}
p {{
    margin: 0 0 6px 0;
    line-height: 1.45;
    text-align: left;
}}
h1, h2, h3, h4, h5, h6 {{
    margin: 8px 0 4px 0;
    font-weight: 700;
}}
h1 {{ font-size: 15px; color: #ffffff; }}
h2 {{ font-size: 13px; color: #f4f4f5; }}
h3 {{ font-size: 12px; color: #e4e4e7; }}
ul, ol {{
    margin-top: 2px;
    margin-bottom: 6px;
    margin-left: 18px;
    padding-left: 0;
    text-align: left;
}}
li {{
    margin-bottom: 2px;
    line-height: 1.4;
    text-align: left;
}}
table {{
    border-collapse: collapse;
    margin: 6px 0;
    border: 1px solid rgba(255, 255, 255, 0.15);
}}
th {{
    background-color: rgba(255, 255, 255, 0.08);
    font-weight: bold;
    padding: 4px 8px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    text-align: left;
}}
td {{
    padding: 4px 8px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    text-align: left;
}}
code {{
    background-color: rgba(255, 255, 255, 0.05);
    color: #93c5fd;
    border-radius: 3px;
    font-family: Consolas, 'Courier New', monospace;
    padding: 1px 3px;
}}
a {{
    color: #60a5fa;
    text-decoration: underline;
}}
.code-block-box {{
    margin: 8px 0;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background-color: #0d0d0d;
}}
.code-header {{
    background-color: #1e1e1e;
    color: #9ca3af;
    font-size: 10px;
    font-weight: 600;
    font-family: Consolas, monospace;
    padding: 4px 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    letter-spacing: 0.5px;
}}
.code-body {{
    background-color: #0d0d0d;
    padding: 8px 10px;
}}
.highlight {{
    background-color: #0d0d0d !important;
    padding: 0;
    margin: 0;
    border: none;
}}

.highlight pre {{
    background-color: #0d0d0d !important;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
    font-size: 11px;
    line-height: 1.45;
    margin: 0;
    padding: 0;
    color: #d4d4d4;
}}
"""


def render_markdown(md_text: Optional[str]) -> str:
    """Render markdown into an HTML body snippet."""
    if not md_text:
        return ""
    try:
        return _MD_PARSER.render(md_text)
    except Exception as exc:
        logger.error("Error rendering markdown: %s", exc)
        # Escape raw characters on fallback
        escaped = (
            str(md_text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        return f"<p>{escaped}</p>"


def render_full_html(md_text: Optional[str]) -> str:
    """Render markdown wrapped in a full HTML document with Ghost AI styles."""
    body = render_markdown(md_text)
    css = get_document_css()
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
