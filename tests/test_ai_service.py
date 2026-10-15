"""
Unit tests for Ghost AI background worker message formatters.
"""

from ghost_ai.ai_service import format_messages_for_openai, format_messages_for_anthropic


def test_format_messages_for_openai():
    raw = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    formatted = format_messages_for_openai(raw, "You are a helpful assistant.")
    assert len(formatted) == 3
    assert formatted[0] == {"role": "system", "content": "You are a helpful assistant."}
    assert formatted[1] == {"role": "user", "content": "Hello"}
    assert formatted[2] == {"role": "assistant", "content": "Hi there!"}


def test_format_messages_for_anthropic():
    raw = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    formatted = format_messages_for_anthropic(raw)
    assert len(formatted) == 2
    assert formatted[0] == {"role": "user", "content": "Hello"}
    assert formatted[1] == {"role": "assistant", "content": "Hi there!"}
