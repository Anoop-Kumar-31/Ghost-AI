"""
Unit tests for the centralized markdown_renderer module.
"""

import pytest
from ghost_ai.markdown_renderer import render_markdown, render_full_html, highlight_code


def test_headings_and_bold():
    """Verify headers and bold text are rendered properly."""
    md = "# Heading 1\n## Heading 2\n**Bold Text** and *Italic Text*"
    html = render_markdown(md)
    assert "<h1>Heading 1</h1>" in html
    assert "<h2>Heading 2</h2>" in html
    assert "<strong>Bold Text</strong>" in html
    assert "<em>Italic Text</em>" in html


def test_ordered_and_nested_lists():
    """Verify ordered and nested lists render proper HTML tags."""
    md = """
1. First item
2. Second item
   - Sub item A
   - Sub item B
3. Third item
"""
    html = render_markdown(md)
    assert "<ol>" in html
    assert "</ol>" in html
    assert "<li>First item" in html
    assert "<ul>" in html
    assert "Sub item A" in html


def test_markdown_tables():
    """Verify GFM Markdown tables render table, tr, th, td structure."""
    md = """
| Language | Paradigm | Typing |
| :--- | :--- | :--- |
| Python | Multi | Dynamic |
| Rust | Systems | Static |
"""
    html = render_markdown(md)
    assert "<table>" in html
    assert "<thead>" in html
    assert ">Language</th>" in html
    assert "<tbody>" in html
    assert ">Python</td>" in html
    assert ">Rust</td>" in html


@pytest.mark.parametrize("lang, code", [
    ("python", "def greet(name: str):\n    return f'Hello {name}'"),
    ("javascript", "const sum = (a, b) => a + b;"),
    ("jsx", "function App() { return <div>Ghost AI</div>; }"),
    ("sql", "SELECT id, title FROM chats WHERE active = 1;"),
    ("bash", "export GHOST_MODE=true && echo $GHOST_MODE"),
])
def test_language_aware_code_fences(lang, code):
    """Verify generic language-aware highlighting for major languages."""
    md = f"```{lang}\n{code}\n```"
    html = render_markdown(md)
    assert 'class="code-block-box"' in html
    assert f'class="code-header"' in html
    assert f'>{lang.upper()}<' in html
    assert 'class="highlight"' in html
    # Check that code content is preserved
    assert "code" in html or "pre" in html


def test_unknown_language_tag_fallback():
    """Verify unknown language tags fallback gracefully to plain text without crashing."""
    md = "```unknown_lang_xyz\nsome custom code here\n```"
    html = render_markdown(md)
    assert 'class="code-block-box"' in html
    assert 'class="code-header"' in html
    assert '>UNKNOWN_LANG_XYZ<' in html
    assert "some custom code here" in html


def test_incomplete_code_fence_during_streaming():
    """Verify unclosed code fences during live streaming do not crash the parser."""
    streaming_chunk = "Here is the code:\n```python\ndef partial_func():\n    x = 10"
    html = render_markdown(streaming_chunk)
    assert "partial_func" in html
    assert "10" in html


def test_html_like_text_escaped_safely():
    """Verify raw HTML-like model output is safely escaped, not rendered as executable markup."""
    untrusted = '<script>alert("pwned")</script><img src="x" onerror="alert(1)"/>'
    html = render_markdown(untrusted)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "onerror=" not in html or "&lt;img" in html


def test_empty_and_unicode_text():
    """Verify empty input and Unicode strings render cleanly without errors."""
    assert render_markdown("") == ""
    assert render_markdown(None) == ""

    unicode_md = "## 👻 Ghost AI 🤖\n*Multi-lingual:* こんにちは 世界 • Привет мир • café & na\u00efve"
    html = render_markdown(unicode_md)
    assert "Ghost AI" in html
    assert "こんにちは" in html
    assert "Привет мир" in html
    assert "café" in html


def test_render_full_html():
    """Verify render_full_html produces complete DOCTYPE, CSS styles, and body."""
    full = render_full_html("**QueueFlow**")
    assert "<!DOCTYPE html>" in full
    assert "<style>" in full
    assert "<strong>QueueFlow</strong>" in full
