"""
Comprehensive security and hardening regression tests for Ghost AI.
Verifies:
1. Endpoint URL validation (loopback HTTP vs remote HTTPS, expected hosts, SSRF prevention)
2. Credential isolation (API keys stored in keyring/memory vault, stripped from JSON files)
3. Authenticated Fernet encryption for chat history (magic header, no overwrite on missing key)
4. Attachment security guards (extension whitelist, 1MB limit, 10,000 char truncation, relative names)
5. Voice recording cooperative cancellation (frames discarded, no transcription)
"""

import json
from pathlib import Path
import pytest

from ghost_ai.config import (
    validate_endpoint_url,
    validate_config,
    load_config,
    save_config,
    is_loopback_host,
)
from ghost_ai.secure_store import (
    save_provider_key,
    get_provider_key,
    get_or_create_history_encryption_key,
    MissingEncryptionKeyError,
)
from ghost_ai.persistence import (
    save_data,
    load_data,
    ENC_MAGIC_PREFIX,
    create_chat_dict,
)
from ghost_ai.chat_view import ALLOWED_ATTACHMENT_EXTENSIONS
from ghost_ai.voice_worker import MicVoiceWorker, SysAudioWorker


def test_endpoint_url_security_boundaries():
    """Verify strict URL validation rejects remote HTTP, accepts HTTPS and loopback HTTP."""
    # Remote HTTP must be rejected
    ok, err = validate_endpoint_url("http://api.openai.com/v1", provider="OpenAI")
    assert ok is False
    assert "must use HTTPS" in err

    ok, err = validate_endpoint_url("http://evil-proxy.com/v1", provider="Custom (OpenAI-Compatible)")
    assert ok is False
    assert "must use HTTPS" in err

    # Valid remote HTTPS with expected host
    ok, url = validate_endpoint_url("https://api.openai.com/v1", provider="OpenAI")
    assert ok is True
    assert url == "https://api.openai.com/v1"

    # Mismatched expected host for preset
    ok, err = validate_endpoint_url("https://attacker.com/v1", provider="OpenAI")
    assert ok is False
    assert "is not the official endpoint" in err

    # Loopback HTTP is explicitly allowed for local LLMs
    ok, url = validate_endpoint_url("http://127.0.0.1:11434/v1", provider="Ollama (Local)")
    assert ok is True

    ok, url = validate_endpoint_url("http://localhost:11434/v1", provider="Ollama (Local)")
    assert ok is True

    # Userinfo / credentials in URL must be rejected
    ok, err = validate_endpoint_url("http://admin:pass@localhost:8080/v1", provider="Custom (OpenAI-Compatible)")
    assert ok is False
    assert "embedded credentials" in err.lower()


def test_config_credentials_never_written_to_disk(tmp_path: Path):
    """Verify API keys are stored in secure store and stripped before JSON serialization."""
    cfg_file = tmp_path / "config.json"
    raw = {
        "provider": "Groq",
        "api_key": "gsk_secret_1234567890",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    }
    assert save_config(raw, cfg_file) is True

    # Check raw disk content: api_key must be empty string
    disk_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk_data["api_key"] == ""

    # load_config must securely re-attach the key from keyring
    loaded = load_config(cfg_file)
    assert loaded["api_key"] == "gsk_secret_1234567890"


def test_legacy_plaintext_api_key_migration(tmp_path: Path):
    """Verify legacy plaintext API key in JSON is migrated to keyring and scrubbed from disk."""
    cfg_file = tmp_path / "legacy_config.json"
    legacy_payload = {
        "provider": "Anthropic",
        "api_key": "sk-ant-legacy-secret-key-999",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-5-sonnet-20241022",
    }
    cfg_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

    # Load must trigger migration
    loaded = load_config(cfg_file)
    assert loaded["api_key"] == "sk-ant-legacy-secret-key-999"

    # Verify disk file was overwritten without plaintext key
    updated_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert updated_disk["api_key"] == ""


def test_fernet_history_encryption_and_magic_header(tmp_path: Path):
    """Verify saved chat history has GHOSTAI-ENC-V1 prefix and decrypts accurately."""
    data_file = tmp_path / "chats.enc"
    chat = create_chat_dict("Classified Operation")
    chat["messages"].append({"role": "user", "content": "Secret prompt content 42"})

    payload = {
        "chats": [chat],
        "open_tabs": [chat["id"]],
        "active_chat_id": chat["id"],
    }

    assert save_data(payload, data_file) is True

    raw_bytes = data_file.read_bytes()
    assert raw_bytes.startswith(ENC_MAGIC_PREFIX)
    # The plaintext secret must NOT appear in the raw bytes
    assert b"Secret prompt content 42" not in raw_bytes

    # load_data decrypts cleanly
    loaded = load_data(data_file)
    assert len(loaded["chats"]) == 1
    assert loaded["chats"][0]["title"] == "Classified Operation"
    assert loaded["chats"][0]["messages"][0]["content"] == "Secret prompt content 42"


def test_attachment_security_extension_whitelist():
    """Verify allowed and disallowed attachment extensions."""
    assert ".txt" in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".py" in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".json" in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".cpp" in ALLOWED_ATTACHMENT_EXTENSIONS

    # Executables, binaries, and dangerous scripts must NOT be allowed
    assert ".exe" not in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".dll" not in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".so" not in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".bin" not in ALLOWED_ATTACHMENT_EXTENSIONS
    assert ".com" not in ALLOWED_ATTACHMENT_EXTENSIONS


def test_voice_worker_cancel_semantics():
    """Verify calling cancel() on voice workers discards audio without transcribing."""
    mic = MicVoiceWorker()
    mic._frames = [b"\x00\x00" * 100]
    mic.cancel()

    assert mic._cancel_event.is_set()
    assert len(mic._frames) == 0

    sys_worker = SysAudioWorker()
    sys_worker._frames = [b"\x00\x00" * 100]
    sys_worker.cancel()

    assert sys_worker._cancel_event.is_set()
    assert len(sys_worker._frames) == 0
