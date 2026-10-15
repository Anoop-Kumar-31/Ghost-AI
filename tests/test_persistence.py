"""
Unit tests for Ghost AI persistence and geometry validation.
Tests run headless and do not require Windows GUI or HWND interactions.
"""

import json
from pathlib import Path
import pytest

from ghost_ai.persistence import (
    load_data,
    save_data,
    sanitize_geometry,
    derive_chat_title,
    create_chat_dict,
    DEFAULT_DATA,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
)


def test_missing_json_file(tmp_path: Path):
    """Test loading from a non-existent file returns sensible defaults."""
    non_existent = tmp_path / "does_not_exist.json"
    data = load_data(non_existent)
    assert data["chats"] == []
    assert data["ghost_mode"] is False
    assert data["geometry"]["width"] == DEFAULT_WIDTH
    assert data["geometry"]["height"] == DEFAULT_HEIGHT
    assert not non_existent.exists()


def test_save_and_load_chats(tmp_path: Path):
    """Test saving and loading multi-chat sessions."""
    target_file = tmp_path / "chats.json"
    chat1 = create_chat_dict("Project Planning")
    chat1["messages"] = [
        {"role": "user", "content": "Help me plan a project", "timestamp": "2026-10-15T12:00:00"},
        {"role": "assistant", "content": "Here is the project outline...", "timestamp": "2026-10-15T12:00:02"},
    ]

    save_payload = {
        "chats": [chat1],
        "active_chat_id": chat1["id"],
        "view_mode": "grid",
        "current_view": "chat",
        "geometry": {"x": 120, "y": 80, "width": 450, "height": 550},
        "ghost_mode": False,
    }

    assert save_data(save_payload, target_file) is True
    assert target_file.is_file()

    loaded = load_data(target_file)
    assert len(loaded["chats"]) == 1
    assert loaded["chats"][0]["title"] == "Project Planning"
    assert len(loaded["chats"][0]["messages"]) == 2
    assert loaded["active_chat_id"] == chat1["id"]
    assert loaded["ghost_mode"] is False


def test_derive_chat_title():
    """Test automatic chat title extraction."""
    assert derive_chat_title("Write a python script to parse logs") == "Write a python script to parse logs"
    assert derive_chat_title("   ") == "New Chat"
    long_prompt = "Explain in extreme detail how the Linux kernel handles virtual memory allocation and page faults"
    derived = derive_chat_title(long_prompt)
    assert len(derived) <= 48
    assert derived.endswith("...")


def test_malformed_json_graceful_recovery(tmp_path: Path):
    """Test that malformed JSON is handled gracefully without crashing or deleting the file."""
    corrupt_file = tmp_path / "chats.json"
    corrupt_file.write_text("{ this is not valid json : [", encoding="utf-8")

    loaded = load_data(corrupt_file)
    assert loaded["chats"] == []
    assert loaded["geometry"]["width"] == DEFAULT_WIDTH

    # Ensure corrupt file is NOT deleted or erased
    assert corrupt_file.exists()
    assert "{ this is not valid json : [" in corrupt_file.read_text(encoding="utf-8")


def test_empty_json_file(tmp_path: Path):
    """Test that an empty file returns default data without raising an exception."""
    empty_file = tmp_path / "chats.json"
    empty_file.write_text("", encoding="utf-8")

    loaded = load_data(empty_file)
    assert loaded == DEFAULT_DATA


def test_atomic_save_behavior(tmp_path: Path):
    """Test that save writes atomically and produces valid formatted JSON."""
    target_file = tmp_path / "subdir" / "chats.json"
    data = {
        "chats": [{"id": "c1", "title": "Test Chat", "messages": []}],
        "geometry": {"x": 200, "y": 150, "width": 420, "height": 560},
        "ghost_mode": False,
    }

    success = save_data(data, target_file)
    assert success is True
    assert target_file.is_file()

    # Verify no dangling temporary files remain
    tmp_files = list((tmp_path / "subdir").glob("*.tmp"))
    assert len(tmp_files) == 0

    # Verify valid JSON
    with open(target_file, "r", encoding="utf-8") as f:
        parsed = json.load(f)
        assert len(parsed["chats"]) == 1
        assert parsed["chats"][0]["title"] == "Test Chat"
