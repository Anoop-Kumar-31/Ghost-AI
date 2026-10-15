"""
Unit tests for Ghost AI configuration management.
"""

from pathlib import Path
from ghost_ai.config import (
    load_config,
    save_config,
    PROVIDER_PRESETS,
    DEFAULT_CONFIG,
)


def test_config_defaults(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg = load_config(cfg_file)
    assert cfg["provider"] == "OpenAI"
    assert cfg["api_key"] == ""
    assert "gpt-4o-mini" in cfg["model"]
    assert cfg["stream"] is True


def test_config_save_and_load(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    sample = {
        "provider": "Groq",
        "api_key": "gsk_test123",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "system_prompt": "Custom prompt",
        "temperature": 0.5,
        "stream": True,
    }
    assert save_config(sample, cfg_file) is True
    loaded = load_config(cfg_file)
    assert loaded["provider"] == "Groq"
    assert loaded["api_key"] == "gsk_test123"
    assert loaded["model"] == "llama-3.3-70b-versatile"


def test_provider_presets():
    assert "OpenAI" in PROVIDER_PRESETS
    assert "OpenRouter" in PROVIDER_PRESETS
    assert "Groq" in PROVIDER_PRESETS
    assert "DeepSeek" in PROVIDER_PRESETS
    assert "Anthropic" in PROVIDER_PRESETS
    assert "Ollama (Local)" in PROVIDER_PRESETS
