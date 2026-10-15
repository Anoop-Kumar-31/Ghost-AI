<div align="center">

<img src="./images/GhostAi.png" alt="Ghost AI Preview" width="90%">

# 👻 Ghost AI
### The Stealth AI Desktop Assistant That Stays Out of Your Way.
*Invisible to Screen Shares • Click-Through Ghost Mode • Multi-Chat History • Bring Your Own Key*

<br/>

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-0078D6.svg?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/Anoop-Kumar-31/Ghost-AI)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-41CD52.svg?style=for-the-badge&logo=qt&logoColor=white)](https://www.qt.io/qt-for-python)
[![Tests](https://img.shields.io/badge/Tests-18%20Passing-success.svg?style=for-the-badge)](tests/)

</div>

---

## ⚡ What is Ghost AI?

**Ghost AI** is a lightweight, frameless, always-on-top desktop AI companion designed for maximum discretion and zero productivity friction. 

Just like **GhostNotes**, Ghost AI features true native OS-level **screen capture invisibility** and **click-through Ghost Mode**, but brings the full power of modern Large Language Models directly to your floating overlay:

- **💬 Real-Time Streaming AI**: Chat with cutting-edge models (GPT-4o, Claude 3.5 Sonnet, DeepSeek, Groq, Ollama) with live streaming text responses.
- **📚 Multi-Chat History**: Browse past conversations in responsive Grid (`⊞`) or List (`☰`) modes, search past dialogues, rename, and delete sessions.
- **🔑 Bring Your Own Key (BYOK)**: Connect your favorite providers directly—OpenAI (ChatGPT), OpenRouter, Groq, DeepSeek, Anthropic, or local Ollama / LM Studio.
- **🛡️ Capture Invisibility**: Completely invisible to screenshots, Zoom, Google Meet, Microsoft Teams, Discord, and OBS via native Win32 `WDA_EXCLUDEFROMCAPTURE` and macOS `NSWindowSharingNone`.
- **👻 Click-Through Ghost Mode**: Toggle click-through transparency with `Ctrl+G` or the blue micro-dot. Clicks pass seamlessly to whatever application is beneath the overlay.
- **🔕 Zero Desktop Clutter**: Excluded from Windows Taskbar, Alt+Tab, macOS Dock, and Cmd+Tab.
- **🎯 Stealth Cursor**: Enforces a strict arrow cursor across the entire UI—no cursor changes that give away text inputs or clickable regions.

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+ (Windows 10/11 or macOS 12+)
- PySide6, requests, and pytest

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/Anoop-Kumar-31/Ghost-AI.git
cd Ghost-AI

# Install dependencies
pip install -r requirements.txt
```

### 3. Launching

```bash
# Direct launch
python main.py

# Windows background silent launch (no console window)
GhostAI.vbs
```

---

## ⚙️ Configuration & Providers

Click the **⚙ Settings** button in the header (or press `Ctrl+,`) to configure your AI provider:

| Provider | Supported Models | Base Endpoint |
| :--- | :--- | :--- |
| **OpenAI** | `gpt-4o-mini`, `gpt-4o`, `o3-mini`, `gpt-3.5-turbo` | `https://api.openai.com/v1` |
| **OpenRouter** | `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`, `deepseek/deepseek-chat` | `https://openrouter.ai/api/v1` |
| **Groq** | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768` | `https://api.groq.com/openai/v1` |
| **DeepSeek** | `deepseek-chat`, `deepseek-reasoner` | `https://api.deepseek.com` |
| **Anthropic** | `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`, `claude-3-opus-20240229` | `https://api.anthropic.com` |
| **Ollama (Local)** | `llama3.2`, `mistral`, `deepseek-r1`, `qwen2.5` | `http://localhost:11434/v1` |
| **Custom** | Any OpenAI-compatible endpoint (LM Studio, LocalAI, vLLM) | Custom URL |

Settings are stored securely and atomically in your local user directory:
- **Windows**: `%LOCALAPPDATA%\GhostAI\config.json`
- **macOS/Linux**: `~/.config/ghost_ai/config.json`

### 🆓 Free AI Setup Guide (OpenRouter Free Models)

You can use Ghost AI **100% free** without adding credit cards or payment info using OpenRouter's free model collection:

1. **Browse Free Models**:
   Visit the official list of free models:
   👉 **[OpenRouter Free Text Models Catalog](https://openrouter.ai/models?max_price=0&output_modalities=text&variant=free&order=most-popular)**  
   *(Popular picks: `meta-llama/llama-3.3-70b-instruct:free`, `deepseek/deepseek-r1:free`, `google/gemini-2.0-flash-exp:free`, `mistralai/mistral-7b-instruct:free`)*

2. **Get Your Free API Key**:
   Create a free account and generate an API key at [openrouter.ai/keys](https://openrouter.ai/keys).

3. **Configure Ghost AI**:
   - In Ghost AI, click the **⚙ Settings** button in the header (or press `Ctrl+,`).
   - Set **AI Provider** to **OpenRouter**.
   - Paste your key into the **API Key** box (`sk-or-v1-...`).
   - In the **Model** field, paste or type the model ID you chose (e.g., `meta-llama/llama-3.3-70b-instruct:free`).
   - Click **Test** to verify connection, then click **Save**.
   - You're ready to chat with AI directly in your floating stealth window!

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Enter` | Send message to AI |
| `Shift + Enter` | Insert newline in message input |
| `Ctrl + G` | Toggle Ghost Mode (Click-through) |
| `Ctrl + N` | Start a new chat session |
| `Ctrl + H` / `Escape` | Return to Home / Chats overview |
| `Ctrl + ,` | Open Settings & API Key modal |
| `Ctrl + Q` | Safely close Ghost AI |

---

## 🧱 Architecture & Technology Stack

```
ghost-ai/
├── ghost_ai/
│   ├── __init__.py           # Package exports & version
│   ├── ai_service.py         # Multi-provider streaming background worker (QThread)
│   ├── chat_view.py          # Active conversation room & message bubbles
│   ├── config.py             # Provider presets & atomic settings persistence
│   ├── controls.py           # Independent HWND for Blue (Ghost) & Red (Close) micro-dots
│   ├── history_view.py       # Responsive Grid & List chat history home page
│   ├── macos_utils.py        # Native macOS Cocoa capture hiding & accessory policy
│   ├── main_window.py        # Frameless main window container & routing
│   ├── persistence.py        # Multi-chat storage & screen geometry validation
│   ├── platform_utils.py     # Cross-platform Win32 / Cocoa dispatch
│   └── win32_utils.py        # Native Win32 WS_EX_TRANSPARENT & WDA_EXCLUDEFROMCAPTURE
├── tests/                    # 18 comprehensive automated unit tests
├── GhostAI.vbs               # Silent Windows launcher
├── requirements.txt          # Python requirements
└── main.py                   # Application entrypoint
```

---

## 🧪 Testing

Run the test suite headless across Windows and macOS platforms:

```bash
python -m pytest tests -v
```

All 18 tests cover:
- Persistence, atomic writing, and corrupt file recovery
- Configuration management and provider presets
- Background streaming payload formatting (OpenAI & Anthropic formats)
- HWND separation and taskbar exclusion
- Win32 click-through and screen capture exclusion

---

## 📄 License

Licensed under the **Apache License, Version 2.0**. See the [LICENSE](LICENSE) file for details.
