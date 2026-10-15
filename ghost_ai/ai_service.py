"""
AI Service and background worker for Ghost AI.
Supports streaming responses from OpenAI-compatible APIs (OpenAI, OpenRouter, Groq, DeepSeek, Ollama)
and Anthropic Claude API.
Runs in a background QThread to keep the UI completely non-blocking and responsive.
"""

import json
import logging
from typing import List, Dict, Any, Optional
import requests
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


def format_messages_for_openai(
    raw_messages: List[Dict[str, Any]],
    system_prompt: str = "",
) -> List[Dict[str, str]]:
    """Format raw message dicts into OpenAI API messages list."""
    formatted: List[Dict[str, str]] = []
    if system_prompt.strip():
        formatted.append({"role": "system", "content": system_prompt.strip()})
    for m in raw_messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if content and role in ("user", "assistant", "system"):
            formatted.append({"role": role, "content": content})
    return formatted


def format_messages_for_anthropic(
    raw_messages: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Format raw messages for Anthropic messages API."""
    formatted: List[Dict[str, str]] = []
    for m in raw_messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            formatted.append({"role": role, "content": content})
    return formatted


class AIChatWorker(QThread):
    """
    Background worker thread that communicates with the LLM API.
    Emits chunk_received for real-time streaming, finished when complete, or error.
    """

    chunk_received = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        messages: List[Dict[str, Any]],
        config: Dict[str, Any],
        parent: Optional[Any] = None,
    ):
        super().__init__(parent)
        self.messages = messages
        self.config = config
        self._is_cancelled = False

    def cancel(self) -> None:
        """Cancel the ongoing request."""
        self._is_cancelled = True

    def run(self) -> None:
        api_key = str(self.config.get("api_key", "")).strip()
        base_url = str(self.config.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        model = str(self.config.get("model", "gpt-4o-mini")).strip()
        provider = str(self.config.get("provider", "OpenAI"))
        system_prompt = str(self.config.get("system_prompt", ""))
        temperature = float(self.config.get("temperature", 0.7))
        stream = bool(self.config.get("stream", True))

        # Check for API key (Ollama local may not need one)
        is_local = "localhost" in base_url or "127.0.0.1" in base_url
        if not api_key and not is_local:
            self.error.emit(
                "API Key is missing!\n\nPlease click ⚙ Settings in the top bar to configure your API key."
            )
            return

        try:
            if provider == "Anthropic" or "anthropic.com" in base_url:
                self._run_anthropic(base_url, api_key, model, system_prompt, temperature, stream)
            else:
                self._run_openai_compatible(base_url, api_key, model, system_prompt, temperature, stream)
        except requests.exceptions.Timeout:
            self.error.emit("Request timed out. Please check your network connection.")
        except requests.exceptions.ConnectionError:
            self.error.emit(f"Failed to connect to {base_url}. Please check your connection or endpoint settings.")
        except Exception as e:
            logger.exception("AI generation error: %s", e)
            self.error.emit(f"Error communicating with AI: {str(e)}")

    def _run_openai_compatible(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        stream: bool,
    ) -> None:
        """Call standard OpenAI-compatible /chat/completions endpoint."""
        url = f"{base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if "openrouter.ai" in base_url:
            headers["HTTP-Referer"] = "https://github.com/Anoop-Kumar-31/Ghost-AI"
            headers["X-Title"] = "Ghost AI"

        formatted_msgs = format_messages_for_openai(self.messages, system_prompt)
        payload = {
            "model": model,
            "messages": formatted_msgs,
            "temperature": temperature,
            "stream": stream,
        }

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=stream,
            timeout=(10, 60),
        )

        if response.status_code != 200:
            self._handle_http_error(response)
            return

        accumulated = []
        if stream:
            for line in response.iter_lines(decode_unicode=True):
                if self._is_cancelled:
                    break
                if not line:
                    continue
                line = line.strip()
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_obj = json.loads(data_str)
                        choices = chunk_obj.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                accumulated.append(content)
                                self.chunk_received.emit(content)
                    except json.JSONDecodeError:
                        continue
        else:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                accumulated.append(content)
                self.chunk_received.emit(content)

        full_text = "".join(accumulated)
        if not self._is_cancelled:
            self.finished.emit(full_text)

    def _run_anthropic(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        stream: bool,
    ) -> None:
        """Call Anthropic /v1/messages endpoint."""
        url = f"{base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        formatted_msgs = format_messages_for_anthropic(self.messages)
        payload = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": 2048,
            "temperature": temperature,
            "stream": stream,
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=stream,
            timeout=(10, 60),
        )

        if response.status_code != 200:
            self._handle_http_error(response)
            return

        accumulated = []
        if stream:
            for line in response.iter_lines(decode_unicode=True):
                if self._is_cancelled:
                    break
                if not line:
                    continue
                line = line.strip()
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    try:
                        chunk_obj = json.loads(data_str)
                        event_type = chunk_obj.get("type")
                        if event_type == "content_block_delta":
                            delta = chunk_obj.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                accumulated.append(text)
                                self.chunk_received.emit(text)
                        elif event_type == "message_stop":
                            break
                    except json.JSONDecodeError:
                        continue
        else:
            data = response.json()
            content_blocks = data.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    accumulated.append(text)
                    self.chunk_received.emit(text)

        full_text = "".join(accumulated)
        if not self._is_cancelled:
            self.finished.emit(full_text)

    def _handle_http_error(self, response: requests.Response) -> None:
        """Emit friendly error messages for HTTP status codes."""
        status = response.status_code
        try:
            err_json = response.json()
            err_msg = ""
            if "error" in err_json:
                err_val = err_json["error"]
                if isinstance(err_val, dict):
                    err_msg = err_val.get("message", "")
                elif isinstance(err_val, str):
                    err_msg = err_val
            elif "message" in err_json:
                err_msg = str(err_json["message"])
        except Exception:
            err_msg = response.text[:200]

        if status == 401:
            msg = f"Invalid API Key (401 Unauthorized).\nPlease verify your API key in ⚙ Settings.\nDetails: {err_msg}"
        elif status == 429:
            msg = f"Rate Limit or Quota Exceeded (429).\nPlease check your AI provider account balance.\nDetails: {err_msg}"
        elif status == 404:
            msg = f"Model or endpoint not found (404).\nPlease check your model name or Base URL.\nDetails: {err_msg}"
        else:
            msg = f"API Error (Status {status}):\n{err_msg or response.reason}"

        self.error.emit(msg)
