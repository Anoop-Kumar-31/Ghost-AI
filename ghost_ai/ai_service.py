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

from .config import validate_endpoint_url

logger = logging.getLogger(__name__)


class RequestCancelled(Exception):
    """Raised when an active AI generation request is cancelled cooperatively."""
    pass


class ContextBudgetExceededError(Exception):
    """Raised when context calculation leaves no available tokens for generation."""
    pass


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


def get_model_context_limit(model_name: str, config_limit: Optional[int] = None) -> int:
    """Return model context token limit or safe fallback."""
    if config_limit and config_limit > 0:
        return config_limit
    model_lower = model_name.lower()
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return limit
    return 16384


def estimate_tokens(text: str) -> int:
    """Rough character-based token estimation (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def trim_conversation(
    raw_messages: List[Dict[str, Any]],
    max_budget_tokens: int = 12000,
    system_prompt: str = "",
    output_reserve: int = 0,
    safety_margin: int = 0,
) -> List[Dict[str, Any]]:
    """
    Trim conversation history to fit strictly within model context budget,
    reserving space for system prompt, generated output tokens, and safety margin.
    Preserves recent complete conversation turns where possible.
    Raises ContextBudgetExceededError if available input tokens <= 0.
    """
    if not raw_messages:
        return []

    system_tokens = estimate_tokens(system_prompt) if system_prompt else 0
    total_deductions = output_reserve + system_tokens + safety_margin
    available_input_tokens = max_budget_tokens - total_deductions

    if available_input_tokens <= 0:
        raise ContextBudgetExceededError(
            f"Context budget exhausted: model limit {max_budget_tokens} tokens is insufficient "
            f"for requested output ({output_reserve}) + system prompt ({system_tokens}) + safety margin ({safety_margin})."
        )

    effective_budget = available_input_tokens
    total_tokens = 0
    kept_reversed: List[Dict[str, Any]] = []

    for i, msg in enumerate(reversed(raw_messages)):
        content = msg.get("content", "")
        tokens = estimate_tokens(content)

        # If the latest user message alone exceeds effective budget, truncate it explicitly
        if i == 0 and tokens > effective_budget:
            char_budget = max(40, (effective_budget - 10) * 4)
            truncated_content = content[:char_budget] + "\n...[truncated to fit model context limit]"
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
    Note: QThread's native finished() signal is preserved exclusively for thread exit detection.
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
        self._accumulated_text: str = ""

    def cancel(self) -> None:
        """Thread-safe cooperative cancellation of the ongoing request and underlying HTTP socket."""
        self._cancel_event.set()
        with self._response_lock:
            resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _execute_http_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        stream: bool,
    ) -> requests.Response:
        """
        Unified safe HTTP request dispatcher with cancellation registration,
        redirect prevention (allow_redirects=False), and bounded timeouts.
        """
        if self._cancel_event.is_set():
            raise RequestCancelled()

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=stream,
                timeout=(5, 15),
                allow_redirects=False,
            )
        except Exception:
            if self._cancel_event.is_set():
                raise RequestCancelled()
            raise

        with self._response_lock:
            self._response = resp
            cancelled = self._cancel_event.is_set()

        if cancelled:
            resp.close()
            raise RequestCancelled()

        # Reject unexpected redirects without sending credentials further
        if resp.is_redirect:
            resp.close()
            raise ValueError(f"Unexpected redirect from endpoint to '{resp.headers.get('Location', '')}' rejected for security.")

        resp.encoding = "utf-8"
        return resp

    def run(self) -> None:
        """
        Sole owner of terminal signal emission (response_finished, cancelled, or error).
        Emits exactly one terminal outcome.
        """
        api_key = str(self.config.get("api_key", "")).strip()
        base_url = str(self.config.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        model = str(self.config.get("model", "gpt-4o-mini")).strip()
        provider = str(self.config.get("provider", "OpenAI"))
        system_prompt = str(self.config.get("system_prompt", ""))
        temperature = float(self.config.get("temperature", 0.7))
        max_tokens = int(self.config.get("max_tokens", 2048))
        stream = bool(self.config.get("stream", True))
        trusted = set(self.config.get("trusted_custom_endpoints", []))

        # Endpoint security validation
        ok, res = validate_endpoint_url(base_url, provider=provider, trusted_endpoints=trusted)
        if not ok:
            self.error.emit(self.request_id, f"Security Policy Blocked Request: {res}")
            return

        # Check for API key (Ollama local may not need one)
        is_local = "localhost" in base_url or "127.0.0.1" in base_url
        if not api_key and not is_local:
            err = "API Key is missing!\n\nPlease click ⚙ Settings in the top bar to configure your API key."
            self.error.emit(self.request_id, err)
            return

        self._accumulated_text = ""

        try:
            if self._cancel_event.is_set():
                raise RequestCancelled()

            if provider == "Anthropic" or "anthropic.com" in base_url:
                result_text = self._run_anthropic(base_url, api_key, model, system_prompt, temperature, max_tokens, stream)
            else:
                result_text = self._run_openai_compatible(base_url, api_key, model, system_prompt, temperature, max_tokens, stream)

            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, self._accumulated_text)
            else:
                self.response_finished.emit(self.request_id, result_text)

        except RequestCancelled:
            self.cancelled.emit(self.request_id, self._accumulated_text)
        except ContextBudgetExceededError as ce:
            self.error.emit(self.request_id, str(ce))
        except requests.exceptions.Timeout:
            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, self._accumulated_text)
            else:
                self.error.emit(self.request_id, "Request timed out. Please verify network connection or endpoint availability.")
        except requests.exceptions.ConnectionError:
            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, self._accumulated_text)
            else:
                # Sanitize error message to avoid logging raw endpoints with secrets
                self.error.emit(self.request_id, f"Failed to connect to endpoint host. Please check your connection settings.")
        except Exception as e:
            if self._cancel_event.is_set():
                self.cancelled.emit(self.request_id, self._accumulated_text)
            else:
                logger.error("AI generation error: %s", type(e).__name__)
                self.error.emit(self.request_id, f"AI Generation Error: {str(e)[:160]}")
        finally:
            with self._response_lock:
                resp = self._response
                self._response = None
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

    def _run_openai_compatible(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> str:
        """Execute request for standard OpenAI-compatible /chat/completions endpoint."""
        url = f"{base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if "openrouter.ai" in base_url:
            headers["HTTP-Referer"] = "https://github.com/Anoop-Kumar-31/Ghost-AI"
            headers["X-Title"] = "Ghost AI"

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

        resp = self._execute_http_request(url, headers, payload, stream)

        try:
            if resp.status_code != 200:
                err_msg = self._extract_http_error(resp)
                resp.close()
                raise ValueError(err_msg)

            accumulated: List[str] = []
            if stream:
                for raw_line in resp.iter_lines():
                    if self._cancel_event.is_set():
                        raise RequestCancelled()
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
                                    self._accumulated_text = "".join(accumulated)
                                    self.chunk_received.emit(self.request_id, content)
                        except json.JSONDecodeError:
                            continue
            else:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    accumulated.append(content)
                    self._accumulated_text = content
                    self.chunk_received.emit(self.request_id, content)

            return "".join(accumulated)
        finally:
            resp.close()

    def _run_anthropic(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> str:
        """Execute request for Anthropic /v1/messages endpoint."""
        url = f"{base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

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

        resp = self._execute_http_request(url, headers, payload, stream)

        try:
            if resp.status_code != 200:
                err_msg = self._extract_http_error(resp)
                resp.close()
                raise ValueError(err_msg)

            accumulated: List[str] = []
            if stream:
                for raw_line in resp.iter_lines():
                    if self._cancel_event.is_set():
                        raise RequestCancelled()
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
                                    self._accumulated_text = "".join(accumulated)
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
                        self._accumulated_text = text
                        self.chunk_received.emit(self.request_id, text)

            return "".join(accumulated)
        finally:
            resp.close()

    def _extract_http_error(self, response: requests.Response) -> str:
        """Extract sanitized, friendly error messages without echoing secrets or authorization tokens."""
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
            err_msg = response.text[:140]

        # Sanitize error detail to never echo headers or keys
        err_msg = str(err_msg).replace("Bearer ", "").strip()

        if status == 401:
            return f"Invalid API Key (401 Unauthorized).\nPlease verify your API key in Settings.\nDetails: {err_msg}"
        elif status == 429:
            return f"Rate Limit or Quota Exceeded (429).\nPlease check your provider account balance.\nDetails: {err_msg}"
        elif status == 404:
            return f"Model or Endpoint Not Found (404).\nPlease verify model name or URL.\nDetails: {err_msg}"
        else:
            return f"API Error (Status {status}):\n{err_msg or response.reason}"
