"""
Secure credential store and key management for Ghost AI.
Uses OS credential manager (Keyring / Windows Credential Manager / macOS Keychain).
Provides authenticated Fernet encryption key storage and API key storage per provider.
"""

import os
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "GhostAI"
HISTORY_KEY_ACCOUNT = "history_encryption_key_v1"

# In-memory fallback dictionary ONLY for environments where OS keyring is unavailable (e.g. headless CI)
_memory_vault = {}


def _get_keyring():
    try:
        import keyring
        return keyring
    except Exception as e:
        logger.warning("Keyring module not available: %s", e)
        return None


def get_provider_key_account(provider: str) -> str:
    """Format standard account name for provider API key."""
    clean_p = provider.strip()
    return f"api-key:{clean_p}"


def save_provider_key(provider: str, api_key: str) -> bool:
    """Save an API key to the OS credential manager."""
    if not provider:
        return False
    account = get_provider_key_account(provider)
    kr = _get_keyring()
    if kr:
        try:
            kr.set_password(KEYRING_SERVICE, account, api_key)
            return True
        except Exception as e:
            logger.error("Failed to store API key in OS credential manager: %s", e)
    _memory_vault[account] = api_key
    return True


def get_provider_key(provider: str) -> str:
    """Retrieve an API key from the OS credential manager."""
    if not provider:
        return ""
    account = get_provider_key_account(provider)
    kr = _get_keyring()
    if kr:
        try:
            key = kr.get_password(KEYRING_SERVICE, account)
            if key is not None:
                return key
        except Exception as e:
            logger.error("Failed to read API key from OS credential manager: %s", e)
    return _memory_vault.get(account, "")


def delete_provider_key(provider: str) -> bool:
    """Delete an API key from the OS credential manager."""
    if not provider:
        return False
    account = get_provider_key_account(provider)
    kr = _get_keyring()
    if kr:
        try:
            kr.delete_password(KEYRING_SERVICE, account)
            return True
        except Exception:
            pass
    _memory_vault.pop(account, None)
    return True


# ---------------------------------------------------------------------------
# History Encryption Key Management
# ---------------------------------------------------------------------------

class MissingEncryptionKeyError(Exception):
    """Raised when an encrypted history file exists but its key is missing from the credential store."""
    pass


def get_or_create_history_encryption_key(allow_create: bool = True) -> bytes:
    """
    Retrieve the Fernet encryption key for local chat history.
    Returns 32 url-safe base64-encoded bytes (44 ASCII bytes) expected by Fernet.
    If allow_create is True, generates and persists a new random key if none exists.
    If allow_create is False (e.g. decrypting existing data) and no key exists,
    raises MissingEncryptionKeyError to prevent overwriting or data loss.
    """
    from cryptography.fernet import Fernet

    kr = _get_keyring()
    stored_str: Optional[str] = None

    if kr:
        try:
            stored_str = kr.get_password(KEYRING_SERVICE, HISTORY_KEY_ACCOUNT)
        except Exception as e:
            logger.warning("Failed to access keyring for history key: %s", e)

    if not stored_str:
        stored_str = _memory_vault.get(HISTORY_KEY_ACCOUNT)

    if stored_str:
        try:
            key_bytes = stored_str.strip().encode("utf-8")
            # Verify valid Fernet key
            Fernet(key_bytes)
            return key_bytes
        except Exception as e:
            logger.error("Corrupted history encryption key in credential store: %s", e)
            raise MissingEncryptionKeyError("Stored encryption key is corrupted or unreadable.") from e

    if not allow_create:
        raise MissingEncryptionKeyError(
            "Encrypted history file detected, but the encryption key is not present in the credential store."
        )

    # Generate new valid Fernet key (32 url-safe base64-encoded bytes, len 44)
    new_key = Fernet.generate_key()
    new_str = new_key.decode("utf-8")

    if kr:
        try:
            kr.set_password(KEYRING_SERVICE, HISTORY_KEY_ACCOUNT, new_str)
        except Exception as e:
            logger.warning("Failed to persist history encryption key to keyring: %s", e)

    _memory_vault[HISTORY_KEY_ACCOUNT] = new_str
    return new_key
