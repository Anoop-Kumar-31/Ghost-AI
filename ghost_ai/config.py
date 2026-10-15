"""
Configuration management for Ghost AI.
Handles API keys, provider endpoints, default models, and system prompts.
Stores configuration in %LOCALAPPDATA%\\GhostAI\\config.json on Windows
or ~/.config/ghost_ai/config.json on macOS/Linux.
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Provider presets
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "o3-mini", "gpt-3.5-turbo"],
        "api_type": "openai",
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
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_type": "openai",
    },
    "Ollama (Local)": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "models": ["llama3.2", "mistral", "qwen2.5", "deepseek-r1"],
        "api_type": "openai",
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
    },
    "Custom (OpenAI-Compatible)": {
        "base_url": "http://localhost:8000/v1",
        "default_model": "custom-model",
        "models": ["custom-model"],
        "api_type": "openai",
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "You are Ghost AI, a stealthy, concise, and highly capable desktop AI assistant. "
    "Provide clear, direct, and well-structured responses. Use markdown when formatting code or lists."
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
}


def get_default_config_path() -> Path:
    """Return the default JSON configuration file path."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / "GhostAI" / "config.json"


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load configuration from disk with fallback to defaults."""
    path = config_path or get_default_config_path()
    if not path.is_file():
        logger.info("Config file not found at %s. Using default config.", path)
        return dict(DEFAULT_CONFIG)

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return dict(DEFAULT_CONFIG)
            data = json.loads(content)

        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)

        result = dict(DEFAULT_CONFIG)
        result.update(data)
        return result
    except Exception as e:
        logger.error("Error reading config from %s: %s. Using default config.", path, e)
        return dict(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> bool:
    """Safely and atomically persist configuration to disk."""
    path = config_path or get_default_config_path()
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
            json.dump(config, tf, indent=2, ensure_ascii=False)
            temp_path = Path(tf.name)

        temp_path.replace(path)
        logger.info("Config saved successfully to %s", path)
        return True
    except Exception as e:
        logger.critical("Failed to save config to %s: %s", path, e)
        return False
