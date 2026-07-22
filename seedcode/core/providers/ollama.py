"""Ollama backend: talks to a local Ollama server.

Uses the native Ollama HTTP API: ``GET /api/tags`` to detect the server and
list installed models, ``POST /api/chat`` (NDJSON stream) for replies. No API
key is involved; the server address is configurable (``ollama_host``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from .base import (
    ModelInfo,
    Provider,
    ProviderError,
    StreamEvent,
    TextDelta,
    ToolCallEvent,
    ToolSpec,
    ValidationResult,
)

if TYPE_CHECKING:
    from ..models import AppConfig, Message

_DETECT_TIMEOUT = 5.0
# Local generation can pause while a model loads into memory; be generous.
_CHAT_TIMEOUT = httpx.Timeout(10.0, read=300.0)


def _not_running(host: str) -> ProviderError:
    return ProviderError(
        f"Ollama is not reachable at {host}. Start it with 'ollama serve' "
        "(install from https://ollama.com) and try again."
    )


def _to_api_ollama(message: "Message") -> dict:
    """Ollama message shape; attaches base64 images when present."""
    api = message.to_api()
    if message.images:
        api["images"] = list(message.images)  # type: ignore[assignment]
    return api


def _to_api_ollama_tools(message: "Message") -> dict:
    """Ollama message shape for tool-calling conversations.

    Assistant tool calls use the OpenAI-style ``tool_calls`` field; result
    messages are role=="tool" with plain content (Ollama pairs them by
    order, it has no call ids).
    """
    if message.role == "tool":
        return {"role": "tool", "content": message.content}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in message.tool_calls
            ],
        }
    return _to_api_ollama(message)


@dataclass
class OllamaProvider(Provider):
    def __post_init__(self) -> None:
        self.id = "ollama"
        self.label = "Ollama (local)"
        self.base_url = ""  # per-user host lives in config.ollama_host
        self.requires_key = False
        self.key_hint = ""

    def validate_key(self, api_key: str) -> ValidationResult:
        """No key needed; 'validation' means the local server responds."""
        return ValidationResult(True, "Ollama needs no API key.")

    def extra_settings(self, config: "AppConfig") -> dict[str, str]:
        return {"host": config.ollama_host}

    def set_extra_setting(
        self, config: "AppConfig", name: str, value: str
    ) -> tuple[bool, str]:
        if name != "host":
            return False, f"{self.label} has no setting '{name}'."
        host = value.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            return False, "host expects a URL like http://localhost:11434."
        config.ollama_host = host
        return True, f"Ollama host set to {host}."

    def detect(self, config: "AppConfig") -> bool:
        """True when the Ollama server answers on the configured host."""
        try:
            response = httpx.get(f"{config.ollama_host}/api/tags", timeout=_DETECT_TIMEOUT)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self, config: "AppConfig") -> list[ModelInfo]:
        try:
            response = httpx.get(f"{config.ollama_host}/api/tags", timeout=_DETECT_TIMEOUT)
            response.raise_for_status()
            entries = response.json().get("models", [])
        except httpx.HTTPError as exc:
            raise _not_running(config.ollama_host) from exc
        except ValueError as exc:
            raise ProviderError("Ollama returned an unreadable model list.") from exc

        models = []
        for entry in entries:
            name = entry.get("name")
            if not name:
                continue
            size = entry.get("size") or 0
            detail = f"{size / 1e9:.1f} GB" if size else ""
            models.append(ModelInfo(id=name, detail=detail))
        if not models:
            raise ProviderError(
                "Ollama is running but has no models installed. "
                "Pull one first, e.g.: ollama pull llama3.2"
            )
        return models

    def supports_images(self, config: "AppConfig") -> bool:
        """Ollama's chat API accepts images natively (vision models use them)."""
        return True

    def stream_chat(self, config: "AppConfig", messages: list["Message"]) -> Iterator[str]:
        payload = {
            "model": config.model,
            "messages": [_to_api_ollama(m) for m in messages],
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST", f"{config.ollama_host}/api/chat", json=payload, timeout=_CHAT_TIMEOUT
            ) as response:
                if response.status_code == 404:
                    raise ProviderError(
                        f"Model '{config.model}' is not installed in Ollama. "
                        f"Run: ollama pull {config.model}  (or pick another via /model)"
                    )
                if response.status_code >= 500:
                    raise ProviderError(
                        f"Ollama had a server error (HTTP {response.status_code}). "
                        "Please try again.",
                        transient=True,
                    )
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(f"Ollama error (HTTP {response.status_code}): {detail}")
                # NDJSON: one JSON object per line until "done": true.
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        raise ProviderError(f"Ollama error: {event['error']}")
                    piece = (event.get("message") or {}).get("content")
                    if piece:
                        yield piece
                    if event.get("done"):
                        return
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Timed out waiting for Ollama. The model may still be loading — try again.",
                transient=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise _not_running(config.ollama_host) from exc

    # --- native tool calling -------------------------------------------------
    def supports_tools(self, config: "AppConfig") -> bool:
        """Attempt native tools; models without support fail at runtime and
        the agent layer falls back to the text protocol."""
        return True

    def stream_chat_with_tools(
        self, config: "AppConfig", messages: list["Message"], tools: list[ToolSpec]
    ) -> Iterator[StreamEvent]:
        payload = {
            "model": config.model,
            "messages": [_to_api_ollama_tools(m) for m in messages],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
            "stream": True,
        }
        call_counter = 0
        try:
            with httpx.stream(
                "POST", f"{config.ollama_host}/api/chat", json=payload, timeout=_CHAT_TIMEOUT
            ) as response:
                if response.status_code == 404:
                    raise ProviderError(
                        f"Model '{config.model}' is not installed in Ollama. "
                        f"Run: ollama pull {config.model}  (or pick another via /model)"
                    )
                if response.status_code >= 500:
                    raise ProviderError(
                        f"Ollama had a server error (HTTP {response.status_code}). "
                        "Please try again.",
                        transient=True,
                    )
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(f"Ollama error (HTTP {response.status_code}): {detail}")
                # NDJSON stream; tool calls arrive with arguments already
                # parsed as objects (no fragment assembly needed). Ollama has
                # no call ids, so synthesize stable ones.
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        raise ProviderError(f"Ollama error: {event['error']}")
                    message = event.get("message") or {}
                    piece = message.get("content")
                    if piece:
                        yield TextDelta(piece)
                    for call in message.get("tool_calls") or []:
                        fn = call.get("function") or {}
                        arguments = fn.get("arguments")
                        if not isinstance(arguments, dict):
                            arguments = {}
                        call_counter += 1
                        yield ToolCallEvent(
                            id=f"call_{call_counter}",
                            name=fn.get("name", ""),
                            arguments=arguments,
                        )
                    if event.get("done"):
                        return
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Timed out waiting for Ollama. The model may still be loading — try again.",
                transient=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise _not_running(config.ollama_host) from exc
