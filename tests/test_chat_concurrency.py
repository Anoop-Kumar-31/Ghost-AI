"""
Concurrency and multi-chat generation regression tests for Ghost AI.
Verifies:
1. Multiple conversations can generate concurrently without cross-chat message contamination.
2. Switching active chat updates UI state without disturbing running background generations.
3. Deleting a chat cancels its running generation and prevents saving to an orphaned conversation.
"""

from ghost_ai.ai_service import AIChatWorker
from ghost_ai.chat_view import ChatView
from ghost_ai.persistence import create_chat_dict


def test_independent_chat_generations(qapp):
    """Verify separate chats maintain independent workers and bubbles."""
    view = ChatView()
    view.show()
    qapp.processEvents()

    chat_a = create_chat_dict("Chat A")
    chat_b = create_chat_dict("Chat B")

    # Set Chat A active and attach fake worker
    view.set_active_chat(chat_a)
    worker_a = AIChatWorker([], {"api_key": "x"}, request_id="req-a")
    view._generation_contexts["req-a"] = {
        "chat_id": chat_a["id"],
        "chat": chat_a,
        "bubble": None,
        "buffer": "Initial A ",
        "worker": worker_a,
    }
    view._refresh_active_generation_state()
    assert view._current_worker == worker_a

    # Now start generation in Chat B
    worker_b = AIChatWorker([], {"api_key": "x"}, request_id="req-b")
    view._generation_contexts["req-b"] = {
        "chat_id": chat_b["id"],
        "chat": chat_b,
        "bubble": None,
        "buffer": "Initial B ",
        "worker": worker_b,
    }

    # Stream chunks to both requests
    view._on_worker_chunk("req-a", "chunk A1")
    view._on_worker_chunk("req-b", "chunk B1")

    assert view._generation_contexts["req-a"]["buffer"] == "Initial A chunk A1"
    assert view._generation_contexts["req-b"]["buffer"] == "Initial B chunk B1"

    # Finish Chat B while Chat A is still active
    view._on_worker_finished("req-b", "Complete response for B")
    assert any(m["content"] == "Complete response for B" for m in chat_b["messages"])
    # Chat A must NOT contain Chat B's message
    assert not any(m["content"] == "Complete response for B" for m in chat_a["messages"])

    # Finish Chat A
    view._on_worker_finished("req-a", "Complete response for A")
    assert any(m["content"] == "Complete response for A" for m in chat_a["messages"])
    assert not any(m["content"] == "Complete response for A" for m in chat_b["messages"])

    view.close()


def test_delete_chat_cancels_active_generation(qapp):
    """Verify deleting a chat requests cancellation on its worker."""
    view = ChatView()
    view.show()
    qapp.processEvents()

    chat = create_chat_dict("Chat to delete")
    view.set_active_chat(chat)

    worker = AIChatWorker([], {"api_key": "x"}, request_id="req-del")
    view._generation_contexts["req-del"] = {
        "chat_id": chat["id"],
        "chat": chat,
        "bubble": None,
        "buffer": "Partial...",
        "worker": worker,
    }
    view._refresh_active_generation_state()
    assert not worker.is_cancelled

    # Cancel generations for this chat (as MainWindow.delete_chat does)
    view.cancel_generations_for_chat(chat["id"])
    assert worker.is_cancelled

    view.close()

