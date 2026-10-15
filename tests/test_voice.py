"""
Unit tests for voice workers and voice UI controls.
"""

import pytest
from PySide6.QtCore import Qt

from ghost_ai.voice_worker import (
    MicVoiceWorker,
    SysAudioWorker,
    _resample_audio,
    _transcribe_audio,
)
from ghost_ai.chat_view import ChatView


def test_voice_workers_lifecycle():
    """Test voice workers initialization and stop flags."""
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
    if dev_idx is not None:
        assert isinstance(dev_idx, int)
        assert isinstance(dev_info, dict)


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
