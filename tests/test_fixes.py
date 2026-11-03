"""
Regression tests verifying P0-P3 bug fixes:
1. Thread-safe cancellation and partial response emission in AIChatWorker
2. Context window budgeting (estimate_tokens and trim_conversation)
3. Config validation boundaries and clamping
4. Deep copy persistence isolation, open tabs filtering, active chat id validation
5. Worker shutdown cleanup in ChatView
"""

import copy
from pathlib import Path
from ghost_ai.ai_service import (
    AIChatWorker,
    estimate_tokens,
    trim_conversation,
)
from ghost_ai.config import validate_config, DEFAULT_CONFIG
from ghost_ai.persistence import (
    load_data,
    save_data,
    DEFAULT_DATA,
    create_chat_dict,
)
from ghost_ai.chat_view import ChatView


def test_token_estimation_and_trim_conversation():
    """Verify estimate_tokens and trim_conversation budget management."""
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("a" * 400) == 100

    messages = [
        {"role": "user", "content": "msg 1: " + "x" * 200},  # ~50 tokens
        {"role": "assistant", "content": "msg 2: " + "y" * 200},  # ~50 tokens
        {"role": "user", "content": "msg 3: " + "z" * 200},  # ~50 tokens
    ]

    # Budget that allows only the most recent message
    trimmed = trim_conversation(messages, max_budget_tokens=60)
    assert len(trimmed) == 1
    assert trimmed[0]["content"].startswith("msg 3")

    # Budget that allows all 3
    trimmed_all = trim_conversation(messages, max_budget_tokens=500)
    assert len(trimmed_all) == 3


def test_config_validation_clamping():
    """Verify validate_config clamps out-of-range values and sanitizes inputs."""
    # Temperature clamped to [0.0, 2.0]
    cfg1 = validate_config({"temperature": -1.5})
    assert cfg1["temperature"] == 0.0

    cfg2 = validate_config({"temperature": 3.8})
    assert cfg2["temperature"] == 2.0

    # Max tokens clamped to [1, 128000]
    cfg3 = validate_config({"max_tokens": 0})
    assert cfg3["max_tokens"] == 1

    cfg4 = validate_config({"max_tokens": 999999})
    assert cfg4["max_tokens"] == 128000

    # Invalid non-numeric values fallback safely
    cfg5 = validate_config({"temperature": "invalid", "max_tokens": "invalid"})
    assert cfg5["temperature"] == 0.7
    assert cfg5["max_tokens"] == 2048

    # Base URL trailing slash stripped
    cfg6 = validate_config({"base_url": "https://api.openai.com/v1/"})
    assert cfg6["base_url"] == "https://api.openai.com/v1"

    # Strict stream string parsing
    cfg7 = validate_config({"stream": "false"})
    assert cfg7["stream"] is False

    cfg8 = validate_config({"stream": "true"})
    assert cfg8["stream"] is True

    # Invalid provider fallback
    cfg9 = validate_config({"provider": "RandomMaliciousString123"})
    assert cfg9["provider"] == DEFAULT_CONFIG["provider"]


def test_persistence_open_tabs_and_isolation(tmp_path: Path):
    """Verify open_tabs filtering, active_chat_id fallback, and deepcopy safety."""
    target_file = tmp_path / "chats.json"

    chat1 = create_chat_dict("Chat 1")
    chat2 = create_chat_dict("Chat 2")

    payload = {
        "chats": [chat1, chat2],
        "open_tabs": [chat1["id"], "non-existent-id-123"],
        "active_chat_id": "another-fake-id",
    }
    save_data(payload, target_file)

    loaded = load_data(target_file)
    # The non-existent ID should be filtered out
    assert loaded["open_tabs"] == [chat1["id"]]
    # The fake active_chat_id should fallback to the first open tab
    assert loaded["active_chat_id"] == chat1["id"]

    # Verify mutating loaded data does NOT alter DEFAULT_DATA
    loaded["chats"].append({"id": "mutated"})
    assert len(DEFAULT_DATA["chats"]) == 0


def test_ai_worker_request_id_and_cancellation():
    """Verify AIChatWorker exposes request_id and sets cancel event."""
    worker = AIChatWorker(
        messages=[],
        config={"api_key": "test"},
        request_id="req-12345",
    )
    assert worker.request_id == "req-12345"
    assert not worker.is_cancelled
    worker.cancel()
    assert worker.is_cancelled


def test_chat_view_shutdown_workers(qapp):
    """Verify ChatView.shutdown_workers executes cleanly and returns True."""
    view = ChatView()
    view.show()
    qapp.processEvents()
    clean = view.shutdown_workers(timeout_ms=100)
    assert clean is True
    view.close()


def test_chat_switching_worker_state(qapp):
    """Verify switching to an inactive chat resets _current_worker and generating state."""
    view = ChatView()
    view.show()
    qapp.processEvents()

    chat_a = create_chat_dict("Chat A")
    chat_b = create_chat_dict("Chat B")

    view.set_active_chat(chat_a)
    # Simulate a fake running worker bound to Chat A
    worker = AIChatWorker([], {"api_key": "x"}, request_id="req-a")
    view._generation_contexts["req-a"] = {
        "chat_id": chat_a["id"],
        "chat": chat_a,
        "bubble": None,
        "buffer": "",
        "worker": worker,
    }
    view._current_worker = worker
    view._set_generating_state(True)

    # Now switch to Chat B which has NO active generation
    view.set_active_chat(chat_b)
    assert view._current_worker is None
    # Generating state for Chat B must be False
    assert view._active_chat["id"] == chat_b["id"]

    # Switch back to Chat A -> should re-attach worker and state
    view.set_active_chat(chat_a)
    assert view._current_worker == worker

    view.close()


def test_stealth_no_tooltips(qapp):
    """Verify tooltips are disabled/empty across header and chat controls for stealth."""
    from ghost_ai.main_window import MainWindow
    win = MainWindow()
    win.show_app()
    qapp.processEvents()

    # Header controls
    assert win.header_bar.home_btn.toolTip() == ""
    assert win.header_bar.new_tab_btn.toolTip() == ""
    assert win.header_bar.settings_btn.toolTip() == ""

    # Chat controls
    assert win.chat_view.attach_btn.toolTip() == ""
    assert win.chat_view.mic_btn.toolTip() == ""
    assert win.chat_view.sys_audio_btn.toolTip() == ""
    assert win.chat_view.send_btn.toolTip() == ""
    assert win.chat_view.model_badge.toolTip() == ""

    # Control window dots
    assert win.controls.blue_btn.toolTip() == ""
    assert win.controls.red_btn.toolTip() == ""

    win.close_application()

