"""
AI Service and background worker for Ghost AI.
Supports streaming responses from OpenAI-compatible APIs (OpenAI, OpenRouter, Groq, DeepSeek, Ollama)
and Anthropic Claude API.
Runs in a background QThread to keep the UI completely non-blocking and responsive.
"""

import json
import logging
import threading
from typing import List, Dict, Any, Optional
import requests
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

# Known model context window limits (tokens)
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "o3-mini": 128000,
    "gpt-3.5-turbo": 16384,
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-opus": 200000,
    "llama-3.3-70b": 128000,
    "llama-3.1-8b": 128000,
    "deepseek-chat": 64000,
    "deepseek-reasoner": 64000,
    "llama3.2": 8192,
    "mistral": 32768,
}


def get_model_context_limit(model_name: str) -> int:
    """Return model context token limit or safe fallback."""
    model_lower = model_name.lower()
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return limit
    return 16384


def estimate_tokens(text: str) -> int:
    """Rough character-based token estimation (~4 chars per token)."""
    return max(1, len(text) // 4)


def trim_conversation(
    raw_messages: List[Dict[str, Any]],
    max_budget_tokens: int = 12000,
    system_prompt: str = "",
    output_reserve: int = 0,
) -> List[Dict[str, Any]]:
    """
    Trim conversation history to fit within model context budget,
    reserving space for system prompt and generated response tokens.
    Always preserves newest messages.
    """
    if not raw_messages:
        return []

    system_tokens = estimate_tokens(system_prompt) if system_prompt else 0
    total_deductions = output_reserve + system_tokens
    if max_budget_tokens > total_deductions + 10:
        effective_budget = max(10, max_budget_tokens - total_deductions)
    else:
        effective_budget = max_budget_tokens

    total_tokens = 0
    kept_reversed: List[Dict[str, Any]] = []

    for i, msg in enumerate(reversed(raw_messages)):
        content = msg.get("content", "")
        tokens = estimate_tokens(content)

        # If the latest message alone exceeds effective budget, truncate it to fit
        if i == 0 and tokens > effective_budget:
            char_budget = max(100, effective_budget * 4)
            truncated_content = content[:char_budget] + "\n...[truncated for context budget]"
            msg_copy = dict(msg)
            msg_copy["content"] = truncated_content
            kept_reversed.append(msg_copy)
            break

        if kept_reversed and (total_tokens + tokens > effective_budget):
            break

        kept_reversed.append(msg)
        total_tokens += tokens

    return list(reversed(kept_reversed))


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
    Emits chunk_received for real-time streaming, response_finished when complete,
    cancelled when aborted with partial content, or error.
    Note: QThread's built-in finished() signal is preserved for thread exit detection.
    """

    chunk_received = Signal(str, str)         # (request_id, chunk)
    response_finished = Signal(str, str)      # (request_id, full_response)
    cancelled = Signal(str, str)              # (request_id, partial_response)
    error = Signal(str, str)                  # (request_id, error_message)

    def __init__(
        self,
        messages: List[Dict[str, Any]],
        config: Dict[str, Any],
        parent: Optional[Any] = None,
        request_id: str = "",
    ):
        super().__init__(parent)
        self.request_id = request_id
        self.messages = messages
        self.config = config
        self._cancel_event = threading.Event()
        self._response: Optional[requests.Response] = None
        self._response_lock = threading.Lock()

    def cancel(self) -> None:
        """Thread-safe cancellation of the ongoing request and underlying HTTP socket."""
        self._cancel_event.set()
        with self._response_lock:
            if self._response is not None:
                try:
                    self._response.close()
                except Exception:
                    pass

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:
        api_key = str(self.config.get("api_key", "")).strip()
        base_url = str(self.config.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        model = str(self.config.get("model", "gpt-4o-mini")).strip()
        provider = str(self.config.get("provider", "OpenAI"))
        system_prompt = str(self.config.get("system_prompt", ""))
        temperature = float(self.config.get("temperature", 0.7))
        max_tokens = int(self.config.get("max_tokens", 2048))
        stream = bool(self.config.get("stream", True))

        # Check for API key (Ollama local may not need one)
        is_local = "localhost" in base_url or "127.0.0.1" in base_url
        if not api_key and not is_local:
            err = "API Key is missing!\n\nPlease click ⚙ Settings in the top bar to configure your API key."
            self.error.emit(self.request_id, err)
            return

        try:
            if provider == "Anthropic" or "anthropic.com" in base_url:
                self._run_anthropic(base_url, api_key, model, system_prompt, temperature, max_tokens, stream)
            else:
                self._run_openai_compatible(base_url, api_key, model, system_prompt, temperature, max_tokens, stream)
        except requests.exceptions.Timeout:
            if not self._cancel_event.is_set():
                self.error.emit(self.request_id, "Request timed out. Please check your network connection.")
        except requests.exceptions.ConnectionError:
            if not self._cancel_event.is_set():
                self.error.emit(self.request_id, f"Failed to connect to {base_url}. Please check your connection or endpoint settings.")
        except Exception as e:
            if not self._cancel_event.is_set():
                logger.exception("AI generation error: %s", e)
                self.error.emit(self.request_id, f"Error communicating with AI: {str(e)}")
        finally:
            with self._response_lock:
                self._response = None

    def _run_openai_compatible(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
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

        # Check cancellation before starting
        if self._cancel_event.is_set():
            self.cancelled.emit(self.request_id, "")
            return

        # Apply conversation context limit before formatting
        context_limit = get_model_context_limit(model)
        trimmed = trim_conversation(
            self.messages,
            max_budget_tokens=context_limit,
            system_prompt=system_prompt,
            output_reserve=max_tokens,
        )
        formatted_msgs = format_messages_for_openai(trimmed, system_prompt)
        payload = {
            "model": model,
            "messages": formatted_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=stream,
                timeout=(10, 20),
            )
            with self._response_lock:
                self._response = resp
                cancelled = self._cancel_event.is_set()
            if cancelled:
                resp.close()
                self.cancelled.emit(self.request_id, "")
                return
        except Exception as e:
            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, "")
                return
            raise e

        resp.encoding = "utf-8"

        if resp.status_code != 200:
            self._handle_http_error(resp)
            return

        accumulated: List[str] = []
        try:
            if stream:
                for raw_line in resp.iter_lines():
                    if self._cancel_event.is_set():
                        break
                    if not raw_line:
                        continue
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    else:
                        line = str(raw_line).strip()
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
                                    self.chunk_received.emit(self.request_id, content)
                        except json.JSONDecodeError:
                            continue
            else:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    accumulated.append(content)
                    self.chunk_received.emit(self.request_id, content)
        except Exception:
            if not self._cancel_event.is_set():
                raise
        finally:
            with self._response_lock:
                if self._response is not None:
                    try:
                        self._response.close()
                    except Exception:
                        pass
                    self._response = None

        full_text = "".join(accumulated)
        if self._cancel_event.is_set():
            self.cancelled.emit(self.request_id, full_text)
        else:
            self.response_finished.emit(self.request_id, full_text)

    def _run_anthropic(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> None:
        """Call Anthropic /v1/messages endpoint."""
        url = f"{base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        # Check cancellation before starting
        if self._cancel_event.is_set():
            self.cancelled.emit(self.request_id, "")
            return

        context_limit = get_model_context_limit(model)
        trimmed = trim_conversation(
            self.messages,
            max_budget_tokens=context_limit,
            system_prompt=system_prompt,
            output_reserve=max_tokens,
        )
        formatted_msgs = format_messages_for_anthropic(trimmed)
        payload = {
            "model": model,
            "messages": formatted_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=stream,
                timeout=(10, 20),
            )
            with self._response_lock:
                self._response = resp
                cancelled = self._cancel_event.is_set()
            if cancelled:
                resp.close()
                self.cancelled.emit(self.request_id, "")
                return
        except Exception as e:
            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, "")
                return
            raise e

        resp.encoding = "utf-8"

        if resp.status_code != 200:
            self._handle_http_error(resp)
            return

        accumulated: List[str] = []
        try:
            if stream:
                for raw_line in resp.iter_lines():
                    if self._cancel_event.is_set():
                        break
                    if not raw_line:
                        continue
                    if isinstance(raw_line, bytes):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                    else:
                        line = str(raw_line).strip()
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
                                    self.chunk_received.emit(self.request_id, text)
                            elif event_type == "message_stop":
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                data = resp.json()
                content_blocks = data.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        accumulated.append(text)
                        self.chunk_received.emit(self.request_id, text)
        except Exception:
            if not self._cancel_event.is_set():
                raise
        finally:
            with self._response_lock:
                if self._response is not None:
                    try:
                        self._response.close()
                    except Exception:
                        pass
                    self._response = None

        full_text = "".join(accumulated)
        if self._cancel_event.is_set():
            self.cancelled.emit(self.request_id, full_text)
        else:
            self.response_finished.emit(self.request_id, full_text)

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

        self.error.emit(self.request_id, msg)

