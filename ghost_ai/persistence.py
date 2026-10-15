"""
Persistence module for Ghost AI.
Handles atomic saving, loading, and geometry validation for multi-chat sessions and settings.
Stores data in %LOCALAPPDATA%\\GhostAI\\chats.json on Windows
or ~/.config/ghost_ai/chats.json on macOS/Linux.
"""

import os
import json
import uuid
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 420
DEFAULT_HEIGHT = 560
MIN_WIDTH = 320
MIN_HEIGHT = 380

DEFAULT_DATA: Dict[str, Any] = {
    "chats": [],
    "active_chat_id": None,
    "view_mode": "grid",
    "current_view": "home",
    "geometry": {
        "x": None,
        "y": None,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
    },
    "ghost_mode": False,
}


def get_default_storage_path() -> Path:
    """Return the default JSON storage file path (%LOCALAPPDATA%\\GhostAI\\chats.json on Windows)."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / "GhostAI" / "chats.json"


def derive_chat_title(first_prompt: str) -> str:
    """Derive a friendly title from the first prompt."""
    prompt = first_prompt.strip()
    if not prompt:
        return "New Chat"
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if lines:
        first = lines[0].lstrip("•-*# ").strip()
        if len(first) > 48:
            return first[:45] + "..."
        return first or "New Chat"
    return "New Chat"


def create_chat_dict(title: str = "New Chat") -> Dict[str, Any]:
    """Create a new chat session data structure."""
    now_iso = datetime.now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "created_at": now_iso,
        "updated_at": now_iso,
        "messages": [],
    }


def load_data(storage_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load chat sessions and geometry from disk.
    Returns default data if file is missing, empty, or malformed.
    Never raises an exception or corrupts/deletes existing files.
    """
    path = storage_path or get_default_storage_path()
    if not path.is_file():
        logger.info("Storage file not found at %s. Using default state.", path)
        return dict(DEFAULT_DATA)

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                logger.warning("Storage file at %s is empty. Using defaults.", path)
                return dict(DEFAULT_DATA)
            data = json.loads(content)

        if not isinstance(data, dict):
            logger.warning("Storage JSON is not an object. Using defaults.")
            return dict(DEFAULT_DATA)

        result = dict(DEFAULT_DATA)

        # Handle chats
        if "chats" in data and isinstance(data["chats"], list):
            result["chats"] = data["chats"]
        else:
            result["chats"] = []

        if "active_chat_id" in data and isinstance(data["active_chat_id"], str):
            result["active_chat_id"] = data["active_chat_id"]
        elif result["chats"]:
            result["active_chat_id"] = result["chats"][0].get("id")

        if "view_mode" in data and data["view_mode"] in ("grid", "list"):
            result["view_mode"] = data["view_mode"]

        if "current_view" in data and data["current_view"] in ("home", "chat"):
            result["current_view"] = data["current_view"]

        # Geometry
        geom = data.get("geometry", {})
        if isinstance(geom, dict):
            result["geometry"] = {
                "x": geom.get("x") if isinstance(geom.get("x"), int) else None,
                "y": geom.get("y") if isinstance(geom.get("y"), int) else None,
                "width": geom.get("width") if isinstance(geom.get("width"), int) else DEFAULT_WIDTH,
                "height": geom.get("height") if isinstance(geom.get("height"), int) else DEFAULT_HEIGHT,
            }

        result["ghost_mode"] = bool(data.get("ghost_mode", False))
        return result

    except Exception as e:
        logger.error("Error reading storage file %s: %s. Using defaults.", path, e)
        return dict(DEFAULT_DATA)


def save_data(data: Dict[str, Any], storage_path: Optional[Path] = None) -> bool:
    """
    Safely and atomically persist chat data to disk.
    Writes to a temporary file first, then atomically replaces the target file.
    """
    path = storage_path or get_default_storage_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(temp_dir),
            delete=False,
            suffix=".tmp",
        ) as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            temp_path = Path(tf.name)

        temp_path.replace(path)
        logger.info("Chat data saved successfully to %s", path)
        return True
    except Exception as e:
        logger.critical("Failed to save chat data to %s: %s", path, e)
        return False


def sanitize_geometry(
    x: Optional[int],
    y: Optional[int],
    width: Optional[int],
    height: Optional[int],
) -> Tuple[int, int, int, int]:
    """
    Validate saved geometry against available desktop screens.
    Enforces minimum dimensions and ensures the window stays accessible on screen.
    """
    w = max(width or DEFAULT_WIDTH, MIN_WIDTH)
    h = max(height or DEFAULT_HEIGHT, MIN_HEIGHT)

    screens = QGuiApplication.screens()
    if not screens or x is None or y is None:
        # Default fallback to center of primary screen
        if screens:
            primary_geo = screens[0].availableGeometry()
            px = primary_geo.x() + (primary_geo.width() - w) // 2
            py = primary_geo.y() + (primary_geo.height() - h) // 2
            return px, py, w, h
        return 100, 100, w, h

    # Check if the title bar area (top 40px) is visible on any screen
    is_visible = False
    for screen in screens:
        geo = screen.availableGeometry()
        if geo.intersects(QRect_from_coords(x, y, min(w, 100), 40)):
            is_visible = True
            break

    if not is_visible:
        primary_geo = screens[0].availableGeometry()
        x = primary_geo.x() + (primary_geo.width() - w) // 2
        y = primary_geo.y() + (primary_geo.height() - h) // 2

    return x, y, w, h


def QRect_from_coords(x: int, y: int, w: int, h: int):
    """Helper to construct QRect without importing QRect top-level if needed."""
    from PySide6.QtCore import QRect
    return QRect(x, y, w, h)
