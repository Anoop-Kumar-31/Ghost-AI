"""Centralized Markdown renderer for Ghost AI.

Markdown is parsed with markdown-it-py. Fenced code is highlighted by Pygments
using inline token styles so the colors are retained by Qt's QTextBrowser.
Code-block copy controls use a ``ghost-copy://`` link; MarkdownBrowser handles
that link and writes the exact original source to the clipboard.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import shlex
from typing import Optional, Tuple

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import RegexLexer
from pygments.lexers import get_lexer_by_name
from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
)
from pygments.util import ClassNotFound

logger = logging.getLogger(__name__)


class GhostDarkStyle(Style):
    """A readable VS Code Dark+-inspired palette for dark chat surfaces."""

    name = "ghost-dark"
    background_color = "#111318"
    default_style = "#D4D4D4"
    styles = {
        Comment: "#6A9955 italic",
        Comment.Preproc: "#C586C0",
        Keyword: "#C586C0",
        Keyword.Constant: "#569CD6",
        Keyword.Declaration: "#569CD6",
        Keyword.Namespace: "#4EC9B0",
        Keyword.Type: "#4EC9B0",
        Name: "#D4D4D4",
        Name.Attribute: "#9CDCFE",
        Name.Builtin: "#4FC1FF",
        Name.Class: "#4EC9B0",
        Name.Constant: "#4FC1FF",
        Name.Decorator: "#DCDCAA",
        Name.Function: "#DCDCAA",
        Name.Tag: "#569CD6",
        Name.Variable: "#9CDCFE",
        Number: "#B5CEA8",
        Operator: "#D4D4D4",
        Punctuation: "#D4D4D4",
        String: "#CE9178",
        String.Escape: "#D7BA7D",
        String.Interpol: "#D7BA7D",
        Error: "#F44747 bg:#3A1D1D",
    }


class RedisLexer(RegexLexer):
    """Small Redis CLI lexer for commands when Pygments lacks a Redis lexer."""

    name = "Redis"
    aliases = ["redis", "redis-cli"]
    filenames = ["*.redis"]

    tokens = {
        "root": [
            (r"\s+", Text),
            (r'"(?:\\.|[^"\\])*"', String.Double),
            (r"'(?:\\.|[^'\\])*'", String.Single),
            (r"#.*$", Comment.Single),
            (
                r"(?i)\b(SET|GET|MGET|MSET|DEL|UNLINK|EXISTS|EXPIRE|PEXPIRE|TTL|PTTL|PERSIST|INCR|INCRBY|DECR|DECRBY|APPEND|STRLEN|HSET|HGET|HMGET|HGETALL|HDEL|HEXISTS|LPUSH|RPUSH|LPOP|RPOP|LRANGE|LLEN|SADD|SREM|SMEMBERS|SISMEMBER|SCARD|ZADD|ZREM|ZRANGE|ZREVRANGE|ZRANK|ZCARD|PUBLISH|SUBSCRIBE|UNSUBSCRIBE|PING|INFO|SELECT|FLUSHDB|FLUSHALL)\b",
                Keyword,
            ),
            (r"(?i)\b(EX|PX|EXAT|PXAT|NX|XX|KEEPTTL|GET|CH|INCR|LIMIT|WITHSCORES|MATCH|COUNT)\b", Keyword.Type),
            (r"\b\d+(?:\.\d+)?\b", Number),
            (r"[A-Za-z_][\w:.-]*", Name.Variable),
            (r"[^\s]+", Text),
        ]
    }


_REDIS_COMMANDS = {
    "SET", "GET", "MGET", "MSET", "DEL", "UNLINK", "EXISTS", "EXPIRE",
    "PEXPIRE", "TTL", "PTTL", "PERSIST", "INCR", "INCRBY", "DECR",
    "DECRBY", "APPEND", "STRLEN", "HSET", "HGET", "HMGET", "HGETALL",
    "HDEL", "HEXISTS", "LPUSH", "RPUSH", "LPOP", "RPOP", "LRANGE",
    "LLEN", "SADD", "SREM", "SMEMBERS", "SISMEMBER", "SCARD", "ZADD",
    "ZREM", "ZRANGE", "ZREVRANGE", "ZRANK", "ZCARD", "PUBLISH",
    "SUBSCRIBE", "UNSUBSCRIBE", "PING", "INFO", "SELECT", "FLUSHDB",
    "FLUSHALL",
}

_LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "yml": "yaml",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "ps1": "powershell",
    "c++": "cpp",
    "cxx": "cpp",
    "h": "c",
    "hpp": "cpp",
    "cs": "csharp",
    "c#": "csharp",
    "postgres": "sql",
    "postgresql": "sql",
    "mysql": "sql",
    "plaintext": "text",
    "txt": "text",
    "plain": "text",
    "md": "markdown",
}

_DISPLAY_NAMES = {
    "bash": "BASH",
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "css": "CSS",
    "diff": "DIFF",
    "html": "HTML",
    "javascript": "JAVASCRIPT",
    "json": "JSON",
    "markdown": "MARKDOWN",
    "powershell": "POWERSHELL",
    "python": "PYTHON",
    "redis": "REDIS",
    "sql": "SQL",
    "text": "TEXT",
    "typescript": "TYPESCRIPT",
    "xml": "XML",
    "yaml": "YAML",
}

_FORMATTER = HtmlFormatter(
    style=GhostDarkStyle,
    noclasses=True,
    nowrap=True,
    ensurenl=False,
)


def _parse_fence_info(info: str) -> Tuple[str, str]:
    """Return (language, optional filename/title) from a Markdown fence info string."""
    if not info:
        return "", ""

    try:
        parts = shlex.split(info, posix=True)
    except ValueError:
        parts = info.strip().split()

    if not parts:
        return "", ""

    language = parts[0].strip().lower()
    title = ""
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if separator and key.lower() in {"title", "filename", "file"}:
            title = value.strip().strip("\"'")
            break
    return language, title


def _detect_language(code: str, language: str = "") -> str:
    """Infer a few unmistakable formats when the model omits the fence language."""
    normalized = (language or "").strip().lower()
    if normalized:
        return _LANGUAGE_ALIASES.get(normalized, normalized)

    stripped = code.strip()
    if not stripped:
        return "text"

    first_line = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    first_word = re.match(r"([A-Za-z]+)", first_line)
    if first_word and first_word.group(1).upper() in _REDIS_COMMANDS:
        return "redis"

    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "json"
        except (ValueError, TypeError):
            pass

    if re.search(r"(?im)^\s*(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE|DELETE\s+FROM)\b", stripped):
        return "sql"

    if re.search(r"(?m)^\s*(def |class |from .+ import |import [A-Za-z_]|if __name__ ==)", stripped):
        return "python"

    if re.search(r"(?m)^\s*(const |let |var |function |import .* from |export )", stripped):
        return "javascript"

    return "text"


def _get_lexer(language: str, code: str):
    """Resolve a Pygments lexer, falling back safely to plain text."""
    normalized = _detect_language(code, language)
    if normalized == "redis":
        return RedisLexer(), normalized
    if normalized in {"", "text", "txt", "plaintext", "plain"}:
        from pygments.lexers.special import TextLexer
        return TextLexer(), "text"

    try:
        return get_lexer_by_name(normalized), normalized
    except ClassNotFound:
        logger.debug("Unknown code language '%s'; using plain text", normalized)
        from pygments.lexers.special import TextLexer
        return TextLexer(), normalized or "text"


def highlight_code(code: str, lang: str = "") -> str:
    """Return syntax-highlighted inline HTML for the supplied source code."""
    if not code:
        return ""

    lexer, _ = _get_lexer(lang, code)
    try:
        return highlight(code, lexer, _FORMATTER)
    except Exception:
        logger.exception("Pygments failed to highlight a code block")
        return html.escape(code)


def _copy_link(code: str) -> str:
    """Build a local custom URL which MarkdownBrowser turns into a clipboard action."""
    payload = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii").rstrip("=")
    return f"ghost-copy://code/{payload}"


def _render_code_container(code: str, language: str = "", title: str = "") -> str:
    lexer, resolved_language = _get_lexer(language, code)
    
    display_code = (
        code[:-2] if code.endswith("\r\n")
        else code[:-1] if code.endswith("\n")
        else code
    )

    highlighted = (
        highlight(display_code, lexer, _FORMATTER)
        if display_code
        else ""
    )
    label = _DISPLAY_NAMES.get(resolved_language, resolved_language.upper() or "TEXT")
    safe_label = html.escape(label)
    safe_title = html.escape(title)
    copy_url = html.escape(_copy_link(code), quote=True)
    title_html = (
        f'<span style="color:#85899a; margin-left:10px;">{safe_title}</span>'
        if safe_title else ""
    )

    return f"""
<table class="ghost-code-block" width="100%" cellspacing="0" cellpadding="0"
       style="width:100%; margin:12px 0; border:1px solid #30323d; background-color:#101116;">
  <tr>
    <td class="ghost-code-header" bgcolor="#1b1d26"
        style="background-color:#1b1d26; padding:3px 6px; border-bottom:1px solid #30323d;">
      <span style="color:#a78bfa; font-family:Consolas,monospace; font-size:10px; font-weight:700;">
        {safe_label}{title_html}
      </span>
    </td>
  </tr>
  <tr>
    <td class="ghost-code-content" bgcolor="#101116"
        style="background-color:#101116; padding:3px 6px;">
      <pre style="margin:0; padding:0; color:#d4d4d4; background-color:#101116; white-space:pre; font-family:'Cascadia Code',Consolas,'Courier New',monospace; font-size:12px; line-height:1.15;"><code>{highlighted}</code></pre>
    </td>
  </tr>
</table>
"""


def _render_fence(self, tokens, idx, options, env):
    """Custom fenced-code renderer with language parsing and a copy action."""
    token = tokens[idx]
    language, title = _parse_fence_info(token.info or "")
    return _render_code_container(token.content, language, title)


def _render_code_block(self, tokens, idx, options, env):
    """Render indented Markdown code blocks as readable plain text blocks."""
    token = tokens[idx]
    return _render_code_container(token.content, "text", "")


def _create_markdown_parser() -> MarkdownIt:
    parser = MarkdownIt("js-default", {"html": False, "linkify": False})
    parser.add_render_rule("fence", _render_fence)
    parser.add_render_rule("code_block", _render_code_block)
    return parser


_MD_PARSER = _create_markdown_parser()


def get_document_css() -> str:
    """Return Markdown CSS that is supported by Qt's rich-text engine."""
    return """
body {
    color: #e5e7eb;
    background-color: transparent;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    margin: 0;
    padding: 0;
}
p { margin: 2px 0 10px 0; line-height: 1.15; }
h1, h2, h3, h4, h5, h6 {
    color: #f4f4f5;
    font-weight: 700;
    margin-top: 16px;
    margin-bottom: 7px;
}
h1 { font-size: 22px; }
h2 { font-size: 18px; }
h3 { font-size: 15px; }
h4 { font-size: 14px; }
ul, ol { margin-top: 3px; margin-bottom: 10px; margin-left: 5px; }
li { margin-bottom: 4px; line-height: 1.15; }
blockquote {
    color: #b8bac6;
    background-color: #151720;
    border-left: 3px solid #8b5cf6;
    margin: 8px 0;
    padding: 6px 10px;
}
a { color: #b9a2ff; text-decoration: none; }
code {
    color: #93c5fd;
    background-color: #20222c;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
    font-size: 11px;
    padding: 1px 4px;
}
pre code {
    color: #d4d4d4;
    background-color: transparent;
    font-size: 12px;
    padding: 0;
}
th, td { padding: 5px 8px; border: 1px solid #343642; }
th { color: #f4f4f5; background-color: #1b1d26; }
hr { border: 0; border-top: 1px solid #30323b; }
"""


def render_markdown(md_text: Optional[str]) -> str:
    """Render Markdown as an HTML body snippet."""
    if not md_text:
        return ""
    try:
        return _MD_PARSER.render(str(md_text))
    except Exception as exc:
        logger.exception("Error rendering Markdown: %s", exc)
        escaped = html.escape(str(md_text)).replace("\n", "<br/>")
        return f"<p>{escaped}</p>"


def render_full_html(md_text: Optional[str]) -> str:
    """Render Markdown wrapped in a complete HTML document."""
    body = render_markdown(md_text)
    css = get_document_css()
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{body}</body></html>"
    )
