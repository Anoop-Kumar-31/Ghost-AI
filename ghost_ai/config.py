"""
Configuration management for Ghost AI.
Handles provider endpoints, default models, and system prompts.
Stores non-secret configuration in %LOCALAPPDATA%\\GhostAI\\config.json on Windows
or ~/.config/ghost_ai/config.json on macOS/Linux.
API keys are stored exclusively in the OS credential manager via ghost_ai.secure_store.
"""

import os
import json
import math
import logging
import tempfile
import ipaddress
from urllib.parse import urlsplit
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Set

from .secure_store import save_provider_key, get_provider_key

logger = logging.getLogger(__name__)

# Provider presets
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "o3-mini", "gpt-3.5-turbo"],
        "api_type": "openai",
        "expected_hosts": {"api.openai.com"},
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1:free",
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-7b-instruct:free",
            "openai/gpt-4o-mini",
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-chat",
        ],
        "api_type": "openai",
        "expected_hosts": {"openrouter.ai"},
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ],
        "api_type": "openai",
        "expected_hosts": {"api.groq.com"},
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_type": "openai",
        "expected_hosts": {"api.deepseek.com"},
    },
    "Ollama (Local)": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "models": ["llama3.2", "mistral", "qwen2.5", "deepseek-r1"],
        "api_type": "openai",
        "expected_hosts": {"localhost", "127.0.0.1", "::1"},
    },
    "Anthropic": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-20241022",
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "api_type": "anthropic",
        "expected_hosts": {"api.anthropic.com"},
    },
    "Custom (OpenAI-Compatible)": {
        "base_url": "http://localhost:8000/v1",
        "default_model": "custom-model",
        "models": ["custom-model"],
        "api_type": "openai",
        "expected_hosts": set(),
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "You are Ghost AI, a stealthy, concise, and highly capable desktop AI assistant.\n"
    "RESPONSE FORMATTING RULES:\n"
    "1. Return normal explanations using clean Markdown headings, paragraphs, lists, and tables.\n"
    "2. Always wrap multi-line programming code in fenced code blocks with the exact language identifier (e.g. ```python, ```javascript, ```cpp, ```sql, ```bash, ```html, ```css, ```rust, ```go, etc.).\n"
    "3. Use inline backticks for variable names, functions, short commands, and keywords.\n"
    "4. Never insert raw HTML for code formatting.\n"
    "5. Keep explanations separate from code blocks and preserve code indentation accurately."
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": "OpenAI",
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "temperature": 0.7,
    "max_tokens": 2048,
    "stream": True,
    "trusted_custom_endpoints": [],
}


def is_loopback_host(hostname: str) -> bool:
    """Check whether a hostname refers strictly to the local loopback interface."""
    if not hostname:
        return False
    host = hostname.strip().lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False


def validate_endpoint_url(
    url: str,
    provider: str = "",
    trusted_endpoints: Optional[Set[str]] = None,
) -> Tuple[bool, str]:
    """
    Strict URL security validation:
    - Rejects malformed URLs, credentials, query strings, and fragments.
    - Allows HTTP ONLY for loopback (localhost / 127.0.0.1 / ::1).
    - Remote endpoints MUST use HTTPS.
    - Verifies expected hostnames for built-in providers.
    - Requires explicit trust for unrecognized custom endpoints.
    Returns (is_valid, reason_or_sanitized_url).
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string."

    url = url.strip()
    try:
        parts = urlsplit(url)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if parts.scheme not in ("http", "https"):
        return False, f"Invalid URL scheme '{parts.scheme}'. Only HTTPS (or local HTTP loopback) is allowed."

    if not parts.hostname:
        return False, "URL has no valid hostname."

    # Reject embedded userinfo (e.g. https://user:pass@example.com)
    if parts.username or parts.password:
        return False, "URL contains embedded credentials, which is forbidden."

    # Reject unexpected query strings and fragments on base URLs
    if parts.query or parts.fragment:
        return False, "Endpoint base URL must not contain query strings or URL fragments."

    is_loopback = is_loopback_host(parts.hostname)

    # Remote non-loopback endpoints MUST use HTTPS
    if not is_loopback and parts.scheme != "https":
        return False, f"Remote endpoint '{parts.hostname}' must use HTTPS to protect API credentials."

    # Verify built-in provider hostnames
    if provider in PROVIDER_PRESETS and provider != "Custom (OpenAI-Compatible)":
        expected = PROVIDER_PRESETS[provider].get("expected_hosts", set())
        if expected and parts.hostname.lower() not in expected:
            # Endpoint host does not match expected host for this provider
            clean_host = parts.hostname.lower()
            if trusted_endpoints and clean_host in trusted_endpoints:
                pass  # Explicitly trusted by user
            else:
                return False, (
                    f"Host '{parts.hostname}' is not the official endpoint for provider '{provider}'. "
                    f"Explicit user confirmation is required."
                )

    sanitized = url.rstrip("/")
    return True, sanitized


def get_default_config_path() -> Path:
    """Return the default JSON configuration file path."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / "GhostAI" / "config.json"


def validate_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize configuration settings strictly against schema boundaries."""
    validated = dict(DEFAULT_CONFIG)
    if not isinstance(raw_config, dict):
        return validated

    # Provider: allow predefined presets or explicit Custom
    raw_provider = raw_config.get("provider")
    if isinstance(raw_provider, str):
        cleaned_p = raw_provider.strip()
        if cleaned_p in PROVIDER_PRESETS:
            validated["provider"] = cleaned_p
        elif cleaned_p.lower().startswith("custom"):
            validated["provider"] = "Custom (OpenAI-Compatible)"

    # Trusted custom endpoints list
    raw_trusted = raw_config.get("trusted_custom_endpoints", [])
    trusted_set = set()
    if isinstance(raw_trusted, list):
        for item in raw_trusted:
            if isinstance(item, str) and item.strip():
                trusted_set.add(item.strip().lower())
    validated["trusted_custom_endpoints"] = list(trusted_set)

    # Base URL validation
    raw_base = raw_config.get("base_url")
    if isinstance(raw_base, str) and raw_base.strip():
        ok, res = validate_endpoint_url(
            raw_base,
            provider=validated["provider"],
            trusted_endpoints=trusted_set,
        )
        if ok:
            validated["base_url"] = res
        else:
            logger.warning("Endpoint validation rejected URL '%s': %s", raw_base, res)
            # Fallback to provider preset base URL
            preset = PROVIDER_PRESETS.get(validated["provider"])
            if preset:
                validated["base_url"] = preset["base_url"]

    # Model
    raw_model = raw_config.get("model")
    if isinstance(raw_model, str) and raw_model.strip():
        validated["model"] = raw_model.strip()

    # API Key: strictly string; loaded from secure store if empty
    raw_key = raw_config.get("api_key")
    if isinstance(raw_key, str):
        validated["api_key"] = raw_key.strip()
    else:
        validated["api_key"] = ""

    # Temperature (explicitly reject boolean True/False as numeric, clamp 0.0 - 2.0, reject NaN/Inf)
    raw_temp = raw_config.get("temperature")
    if isinstance(raw_temp, bool):
        validated["temperature"] = 0.7
    else:
        try:
            temp = float(raw_temp)
            if math.isnan(temp) or math.isinf(temp):
                validated["temperature"] = 0.7
            else:
                validated["temperature"] = max(0.0, min(2.0, temp))
        except (ValueError, TypeError):
            validated["temperature"] = 0.7

    # Max tokens (explicitly reject boolean, clamp to [1, 128000])
    raw_tokens = raw_config.get("max_tokens")
    if isinstance(raw_tokens, bool):
        validated["max_tokens"] = 2048
    else:
        try:
            tokens = int(raw_tokens)
            validated["max_tokens"] = max(1, min(128000, tokens))
        except (ValueError, TypeError):
            validated["max_tokens"] = 2048

    # Stream (strict bool and string parsing)
    raw_stream = raw_config.get("stream")
    if isinstance(raw_stream, str):
        validated["stream"] = raw_stream.strip().lower() in ("true", "1", "yes")
    elif isinstance(raw_stream, bool):
        validated["stream"] = raw_stream
    elif raw_stream is not None:
        validated["stream"] = bool(raw_stream)
    else:
        validated["stream"] = True

    # System prompt
    raw_prompt = raw_config.get("system_prompt")
    if isinstance(raw_prompt, str):
        validated["system_prompt"] = raw_prompt
    else:
        validated["system_prompt"] = DEFAULT_SYSTEM_PROMPT

    return validated


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from disk with migration of any legacy plaintext API keys
    into the OS credential manager. Secrets are never saved back to disk.
    """
    path = config_path or get_default_config_path()
    try:
        if not path.is_file():
            logger.info("Config file not found at %s. Using default config.", path)
            cfg = dict(DEFAULT_CONFIG)
            cfg["api_key"] = get_provider_key(cfg["provider"])
            return cfg

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                cfg = dict(DEFAULT_CONFIG)
                cfg["api_key"] = get_provider_key(cfg["provider"])
                return cfg
            data = json.loads(content)

        if not isinstance(data, dict):
            cfg = dict(DEFAULT_CONFIG)
            cfg["api_key"] = get_provider_key(cfg["provider"])
            return cfg

        # Migration: check if a legacy plaintext api_key exists on disk
        legacy_key = str(data.get("api_key", "")).strip()
        provider = str(data.get("provider", "OpenAI")).strip()
        if legacy_key:
            logger.info("Migrating legacy plaintext API key for provider '%s' to OS credential manager", provider)
            save_provider_key(provider, legacy_key)
            # Re-save config without the secret
            data["api_key"] = ""
            save_config(data, config_path=path)

        validated = validate_config(data)
        # Load active provider's API key from the secure store
        validated["api_key"] = get_provider_key(validated["provider"])
        return validated
    except Exception as e:
        logger.error("Error reading config from %s: %s. Using default config.", path, e)
        cfg = dict(DEFAULT_CONFIG)
        cfg["api_key"] = get_provider_key(cfg["provider"])
        return cfg


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> bool:
    """
    Safely and atomically persist configuration to disk.
    API keys are saved to the OS credential manager and STRIPPED from JSON.
    """
    path = config_path or get_default_config_path()
    try:
        validated = validate_config(config)

        # Save API key to OS credential manager if provided
        key = str(config.get("api_key", "")).strip()
        provider = validated["provider"]
        if key:
            save_provider_key(provider, key)

        # Prepare secret-free copy for disk storage
        safe_copy = dict(validated)
        safe_copy["api_key"] = ""  # Never write API keys into JSON

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = path.parent
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(temp_dir),
            delete=False,
            suffix=".tmp",
        ) as tf:
            json.dump(safe_copy, tf, indent=2, ensure_ascii=False)
            temp_path = Path(tf.name)

        temp_path.replace(path)
        logger.info("Config saved successfully to %s (credentials secured)", path)
        return True
    except Exception as e:
        logger.critical("Failed to save config to %s: %s", path, e)
        return False
