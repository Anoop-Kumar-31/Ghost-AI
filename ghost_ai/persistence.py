"""
Persistence module for Ghost AI with authenticated encryption at rest (Fernet AES-128-CBC + HMAC-SHA256).
Handles atomic saving, loading, geometry validation, and migration of legacy plaintext data.
Encrypted files are identified by the header prefix: GHOSTAI-ENC-V1:
"""

import os
import json
import uuid
import copy
import shutil
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from PySide6.QtGui import QGuiApplication

from .secure_store import (
    get_or_create_history_encryption_key,
    MissingEncryptionKeyError,
)

logger = logging.getLogger(__name__)

ENC_MAGIC_PREFIX = b"GHOSTAI-ENC-V1:"

DEFAULT_WIDTH = 700
DEFAULT_HEIGHT = 700
MIN_WIDTH = 360
MIN_HEIGHT = 420

DEFAULT_DATA: Dict[str, Any] = {
    "chats": [],
    "open_tabs": [],
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


def _get_fernet(key: bytes):
    from cryptography.fernet import Fernet
    return Fernet(key)


def get_default_storage_path() -> Path:
    """Return the default storage file path (%LOCALAPPDATA%\\GhostAI\\chats.dat or chats.json on Windows)."""
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
    Load chat sessions and geometry from disk with authenticated decryption.
    Detects and safely migrates legacy plaintext files.
    NEVER overwrites or erases unreadable encrypted files with default data.
    """
    path = storage_path or get_default_storage_path()
    try:
        if not path.is_file():
            logger.info("Storage file not found at %s. Using default state.", path)
            return copy.deepcopy(DEFAULT_DATA)

        with open(path, "rb") as f:
            raw_bytes = f.read().strip()

        if not raw_bytes:
            logger.warning("Storage file at %s is empty. Using defaults.", path)
            return copy.deepcopy(DEFAULT_DATA)

        # Check for encrypted file header
        if raw_bytes.startswith(ENC_MAGIC_PREFIX):
            cipher_payload = raw_bytes[len(ENC_MAGIC_PREFIX):]
            # Must NOT create a new key when decrypting existing encrypted data!
            key = get_or_create_history_encryption_key(allow_create=False)
            fernet = _get_fernet(key)
            try:
                decrypted_bytes = fernet.decrypt(cipher_payload)
            except Exception as e:
                logger.critical("Failed to decrypt chat history at %s (Invalid key or data corruption): %s", path, e)
                raise ValueError(
                    f"Unable to decrypt chat history file '{path.name}'. "
                    "The encryption key does not match or the data is corrupt. "
                    "File has NOT been overwritten."
                ) from e
            json_text = decrypted_bytes.decode("utf-8")
            data = json.loads(json_text)
        else:
            # Legacy plaintext JSON file detected -> parse and prepare for encrypted migration
            logger.info("Legacy plaintext chat history detected at %s. Migrating to encrypted storage.", path)
            json_text = raw_bytes.decode("utf-8")
            data = json.loads(json_text)
            # Create a backup before migration
            backup_path = path.with_suffix(".json.bak")
            if not backup_path.exists():
                try:
                    shutil.copy2(path, backup_path)
                    logger.info("Plaintext backup created at %s", backup_path)
                except Exception as be:
                    logger.warning("Could not create migration backup: %s", be)

        if not isinstance(data, dict):
            logger.warning("Storage JSON is not an object. Using defaults.")
            return copy.deepcopy(DEFAULT_DATA)

        result = copy.deepcopy(DEFAULT_DATA)

        # Handle chats
        if "chats" in data and isinstance(data["chats"], list):
            result["chats"] = [c for c in data["chats"] if isinstance(c, dict) and "id" in c]
        else:
            result["chats"] = []

        valid_ids = {c["id"] for c in result["chats"]}

        # Handle open tabs: validate against valid chat IDs
        if "open_tabs" in data and isinstance(data["open_tabs"], list):
            result["open_tabs"] = [tid for tid in data["open_tabs"] if tid in valid_ids]
        else:
            result["open_tabs"] = [c["id"] for c in result["chats"][:3]] if result["chats"] else []

        # Handle active_chat_id: must be a valid existing chat
        if "active_chat_id" in data and data["active_chat_id"] in valid_ids:
            result["active_chat_id"] = data["active_chat_id"]
        elif result["open_tabs"]:
            result["active_chat_id"] = result["open_tabs"][0]
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

    except MissingEncryptionKeyError:
        logger.critical("Encrypted history key missing from credential store for %s. Aborting load to protect file.", path)
        raise
    except json.JSONDecodeError as e:
        logger.error("JSON decode error in storage file %s: %s", path, e)
        return copy.deepcopy(DEFAULT_DATA)
    except Exception as e:
        logger.error("Error reading storage file %s: %s", path, e)
        raise


def save_data(data: Dict[str, Any], storage_path: Optional[Path] = None) -> bool:
    """
    Safely and atomically persist chat data to disk using Fernet encryption.
    Writes encrypted payload to a temporary file, then atomically replaces target.
    """
    path = storage_path or get_default_storage_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = get_or_create_history_encryption_key(allow_create=True)
        fernet = _get_fernet(key)

        serialized = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        encrypted_payload = fernet.encrypt(serialized)

        temp_dir = path.parent
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(temp_dir),
            delete=False,
            suffix=".tmp",
        ) as tf:
            tf.write(ENC_MAGIC_PREFIX + encrypted_payload)
            temp_path = Path(tf.name)

        temp_path.replace(path)
        logger.info("Chat data encrypted and saved successfully to %s", path)
        return True
    except Exception as e:
        logger.critical("Failed to save encrypted chat data to %s: %s", path, e)
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
        if screens:
            primary_geo = screens[0].availableGeometry()
            px = primary_geo.x() + (primary_geo.width() - w) // 2
            py = primary_geo.y() + (primary_geo.height() - h) // 2
            return px, py, w, h
        return 100, 100, w, h

    from PySide6.QtCore import QRect
    is_visible = False
    for screen in screens:
        geo = screen.availableGeometry()
        if geo.intersects(QRect(x, y, min(w, 100), 40)):
            is_visible = True
            break

    if not is_visible:
        primary_geo = screens[0].availableGeometry()
        x = primary_geo.x() + (primary_geo.width() - w) // 2
        y = primary_geo.y() + (primary_geo.height() - h) // 2

    return x, y, w, h
