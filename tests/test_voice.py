"""
Unit tests for voice workers and code formatting.
"""

import pytest
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ghost_ai.voice_worker import (
    MicVoiceWorker,
    SysAudioWorker,
    _whisper_lock,
)
from ghost_ai.chat_view import MessageBubble, ChatView


def test_voice_workers_lifecycle(qapp):
    """Test voice workers initialization and stop methods."""
    mic = MicVoiceWorker()
    assert not mic._stop_flag.is_set()
    mic.stop()
    assert mic._stop_flag.is_set()

    sys_w = SysAudioWorker()
    assert not sys_w._stop_flag.is_set()
    sys_w.stop()
    assert sys_w._stop_flag.is_set()


def test_sys_audio_device_lookup():
    """Test loopback device lookup function without raising errors."""
    dev_idx, dev_info = SysAudioWorker.find_loopback_device()
    # On Windows machines with Stereo Mix or loopback this will find an int index
    if dev_idx is not None:
        assert isinstance(dev_idx, int)
        assert isinstance(dev_info, dict)


def test_code_block_vs_code_formatting(qapp):
    """Verify that fenced code blocks render with VS Code dark styling and language headers."""
    code_md = "Here is Python code:\n```python\ndef test():\n    return 42\n```\nDone."
    bubble = MessageBubble("assistant", code_md)
    qapp.processEvents()

    html = bubble.text_lbl.toHtml()
    # Check that language header tag is present
    assert "PYTHON" in html
    # Check that code elements are rendered
    assert "test" in html
    assert "42" in html
    # ArrowCursor strictly maintained
    assert bubble.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert bubble.text_lbl.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_chat_view_voice_buttons(qapp, monkeypatch):
    """Verify ChatView includes mic and system audio buttons with stealth cursor."""
    view = ChatView()
    view.show()
    qapp.processEvents()

    assert view.mic_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert view.sys_audio_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert view.mic_btn.text() == "🎙️"
    assert view.sys_audio_btn.text() == "🔊"

    # Avoid opening real audio hardware in headless test environment
    monkeypatch.setattr(MicVoiceWorker, "start", lambda self: None)
    monkeypatch.setattr(SysAudioWorker, "start", lambda self: None)

    # Test toggling microphone button updates label
    view._toggle_mic_recording()
    assert view.mic_btn.text() == "⏹"
    assert not view.voice_status_frame.isHidden()

    # Test transcription callback inserting text into input
    view._on_mic_transcribed("How do I implement debounce in React?")
    assert "How do I implement debounce in React?" in view.input_edit.toPlainText()

    # Test system audio transcription callback
    view._on_sys_transcribed("Can you explain the virtual DOM?")
    assert "Interviewer asked: Can you explain the virtual DOM?" in view.input_edit.toPlainText()

    # Cancel recording resets UI
    view._cancel_voice_recording()
    assert view.mic_btn.text() == "🎙️"
    assert view.voice_status_frame.isHidden()
    view.close()
