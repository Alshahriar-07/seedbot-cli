"""OpenRouter backend: the openrouter.ai catalogue with Free/Pro modes.

Fully independent provider: its own key slot, base URL, client cache, and
catalogue. Two modes share the same API key:

* **Free Models** (default) — the model picker shows only zero-cost models.
* **Pro Models** — the picker shows paid models.

The mode is a provider-specific setting persisted in OpenRouter's own
config entry. Nothing is hardcoded and no other provider's logic is used.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from ..streaming import iter_stream
from ...utils.logger import get_logger
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

_log = get_logger("openrouter")

_BASE_URL = "https://openrouter.ai/api/v1"
_VALIDATE_URL = f"{_BASE_URL}/key"
_MODELS_URL = f"{_BASE_URL}/models"
_TIMEOUT = 20.0
_CHAT_TIMEOUT = httpx.Timeout(20.0, read=180.0)
_HEADERS = {
    "HTTP-Referer": "https://github.com/Alshahriar-07/seedcode-cli",
    "X-Title": "Seed Code",
}


# Model-list modes (persisted in OpenRouter's own options; same API key).
MODE_FREE = "free"
MODE_PRO = "pro"


def _entry_is_free(entry: dict[str, Any]) -> bool:
    """True when both prompt and completion pricing are exactly zero."""
    pricing = entry.get("pricing") or {}
    try:
        return float(pricing.get("prompt", 1)) == 0.0 and float(
            pricing.get("completion", 1)
        ) == 0.0
    except (TypeError, ValueError):
        return False


@dataclass
class OpenRouterProvider(Provider):
    # Private per-provider client cache (key -> client); never shared.
    _client: Any = field(init=False, default=None, repr=False)
    _client_key: str = field(init=False, default="", repr=False)

    def __post_init__(self) -> None:
        self.id = "openrouter"
        self.label = "OpenRouter"
        self.base_url = _BASE_URL
        self.requires_key = True
        self.key_hint = "create a key at https://openrouter.ai/keys"

    def validate_key(self, api_key: str) -> ValidationResult:
        """Validate with a real authenticated request — no heuristics."""
        key = api_key.strip()
        if not key:
            return ValidationResult(False, "API key is empty.")
        try:
            response = httpx.get(
                _VALIDATE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=_TIMEOUT
            )
        except httpx.TimeoutException:
            return ValidationResult(False, "Validation timed out. Check your connection.")
        except httpx.HTTPError:
            return ValidationResult(False, "Could not reach OpenRouter. Check your connection.")
        if response.status_code == 200:
            return ValidationResult(True, "API key verified.")
        if response.status_code in (401, 403):
            return ValidationResult(False, "API key was rejected by OpenRouter.")
        return ValidationResult(
            False, f"Unexpected response from OpenRouter (HTTP {response.status_code})."
        )

    def mode(self, config: "AppConfig") -> str:
        """Current model-list mode: 'free' (default) or 'pro'."""
        raw = (config.provider_options("openrouter").get("mode") or MODE_FREE).lower()
        return raw if raw in (MODE_FREE, MODE_PRO) else MODE_FREE

    def extra_settings(self, config: "AppConfig") -> dict[str, str]:
        return {"mode": f"{self.mode(config)}  (free = zero-cost models, pro = paid models)"}

    def set_extra_setting(
        self, config: "AppConfig", name: str, value: str
    ) -> tuple[bool, str]:
        if name != "mode":
            return False, f"{self.label} has no setting '{name}'."
        mode = value.strip().lower()
        if mode not in (MODE_FREE, MODE_PRO):
            return False, "mode expects 'free' or 'pro'."
        config.provider_options("openrouter")["mode"] = mode
        return True, f"OpenRouter mode set to {mode} — /model now lists {mode} models."

    def list_models(self, config: "AppConfig") -> list[ModelInfo]:
        """The live catalogue for the CURRENT mode (free or pro models)."""
        try:
            response = httpx.get(_MODELS_URL, timeout=_TIMEOUT)
            response.raise_for_status()
            data = response.json().get("data", [])
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Timed out fetching the OpenRouter model list.", transient=True
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "Could not fetch the OpenRouter model list. Check your connection.",
                transient=True,
            ) from exc

        want_free = self.mode(config) == MODE_FREE
        models = []
        for entry in data:
            if not entry.get("id"):
                continue
            free = _entry_is_free(entry)
            if free is not want_free:
                continue
            models.append(
                ModelInfo(
                    id=entry["id"],
                    label=entry.get("name") or entry["id"],
                    detail=f"{'free' if free else 'paid'} · {entry.get('context_length') or '?'} ctx",
                    is_free=free,
                )
            )
        models.sort(key=lambda m: m.id)
        if not models:
            raise ProviderError(
                f"OpenRouter has no {self.mode(config)} models right now. "
                "Switch mode in /settings (mode free|pro)."
            )
        return models

    def supports_images(self, config: "AppConfig") -> bool:
        """OpenRouter routes to many vision models; let it try image parts."""
        return True

    def stream_chat(self, config: "AppConfig", messages: list["Message"]) -> Iterator[str]:
        # Heavy SDK import deferred to first use; client cached per key.
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        client = self._get_client(config)
        max_tokens = config.effective_max_tokens()
        _log.debug("chat request: model=%s max_tokens=%d", config.model, max_tokens)
        try:
            stream = client.chat.completions.create(
                model=config.model,
                messages=[_to_api_multimodal(m) for m in messages],  # type: ignore[arg-type]
                max_tokens=max_tokens,
                stream=True,
            )
            yield from iter_stream(stream)
        except AuthenticationError as exc:
            raise ProviderError(
                "Authentication failed. Your OpenRouter key may be invalid — run /apikey."
            ) from exc
        except RateLimitError as exc:
            raise ProviderError(
                "Rate limited by OpenRouter. Please wait and try again.", transient=True
            ) from exc
        except APITimeoutError as exc:
            raise ProviderError(
                "The OpenRouter request timed out. Please try again.", transient=True
            ) from exc
        except APIConnectionError as exc:
            raise ProviderError(
                "Network error reaching OpenRouter. Check your connection.", transient=True
            ) from exc
        except APIError as exc:
            raise _friendly_api_error(exc, config.model) from exc

    # --- native tool calling -------------------------------------------------
    def supports_tools(self, config: "AppConfig") -> bool:
        """OpenRouter forwards OpenAI-style tools to capable models."""
        return True

    def stream_chat_with_tools(
        self, config: "AppConfig", messages: list["Message"], tools: list[ToolSpec]
    ) -> Iterator[StreamEvent]:
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        )

        client = self._get_client(config)
        max_tokens = config.effective_max_tokens()
        _log.debug(
            "tool chat request: model=%s max_tokens=%d tools=%d",
            config.model, max_tokens, len(tools),
        )
        try:
            stream = client.chat.completions.create(
                model=config.model,
                messages=[_to_api_tools(m) for m in messages],  # type: ignore[arg-type]
                max_tokens=max_tokens,
                tools=[
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
                stream=True,
            )
            yield from _iter_tool_stream(stream)
        except AuthenticationError as exc:
            raise ProviderError(
                "Authentication failed. Your OpenRouter key may be invalid — run /apikey."
            ) from exc
        except RateLimitError as exc:
            raise ProviderError(
                "Rate limited by OpenRouter. Please wait and try again.", transient=True
            ) from exc
        except APITimeoutError as exc:
            raise ProviderError(
                "The OpenRouter request timed out. Please try again.", transient=True
            ) from exc
        except APIConnectionError as exc:
            raise ProviderError(
                "Network error reaching OpenRouter. Check your connection.", transient=True
            ) from exc
        except APIError as exc:
            raise _friendly_api_error(exc, config.model) from exc

    def _get_client(self, config: "AppConfig") -> Any:
        """Cached OpenAI client for the current key (SDK import deferred)."""
        from openai import OpenAI

        api_key = config.get_api_key("openrouter")
        if self._client is None or self._client_key != api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=_BASE_URL,
                default_headers=_HEADERS,
                timeout=_CHAT_TIMEOUT,
                max_retries=0,  # the engine owns retry policy
            )
            self._client_key = api_key
        return self._client


def _to_api_multimodal(message: "Message") -> dict[str, Any]:
    """Message shape for the API: plain text, or content-parts with images.

    Messages without attachments keep the simple string form (maximum model
    compatibility); desktop screenshots become OpenAI-style image_url parts.
    """
    if not message.images:
        return message.to_api()
    parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
    parts += [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
        for img in message.images
    ]
    return {"role": message.role, "content": parts}


def _to_api_tools(message: "Message") -> dict[str, Any]:
    """OpenAI wire shape for a message in a tool-calling conversation."""
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ],
        }
    return _to_api_multimodal(message)


def _iter_tool_stream(stream: Any) -> Iterator[StreamEvent]:
    """Assemble OpenAI streaming chunks into text deltas and complete calls.

    ``delta.tool_calls`` fragments are keyed by index: the id and function
    name arrive on the first fragment, argument JSON streams in pieces. Each
    call is emitted once, after the stream ends, when its JSON is whole.
    """
    pending: dict[int, dict[str, str]] = {}  # index -> {id, name, args}
    for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = choices[0].delta
        if getattr(delta, "content", None):
            yield TextDelta(delta.content)
        for fragment in getattr(delta, "tool_calls", None) or []:
            slot = pending.setdefault(
                fragment.index, {"id": "", "name": "", "args": ""}
            )
            if getattr(fragment, "id", None):
                slot["id"] = fragment.id
            fn = getattr(fragment, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["args"] += fn.arguments
    for index in sorted(pending):
        slot = pending[index]
        raw = slot["args"].strip() or "{}"
        try:
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
            yield ToolCallEvent(id=slot["id"], name=slot["name"], arguments=arguments)
        except ValueError as exc:
            yield ToolCallEvent(
                id=slot["id"], name=slot["name"], arguments={},
                error=f"Tool call arguments were not valid JSON: {exc}",
            )


def _friendly_api_error(exc: Any, model: str) -> ProviderError:
    """Translate OpenRouter API errors into actionable user messages."""
    status = getattr(exc, "status_code", None)
    detail = getattr(exc, "message", str(exc)) or "Unknown API error."
    if status == 402:
        return ProviderError(
            "OpenRouter rejected the request for lack of credits (HTTP 402). "
            "Pick a free model with /model (filter: free), or add credits."
        )
    if status == 403:
        return ProviderError(
            "OpenRouter refused the request (HTTP 403). Your key may lack access "
            "to this model — pick another with /model."
        )
    if status == 404:
        return ProviderError(
            f"Model '{model}' was not found on OpenRouter. Pick another with /model."
        )
    if status == 408:
        return ProviderError(
            "OpenRouter timed out handling the request. Please try again.", transient=True
        )
    if status is not None and status >= 500:
        return ProviderError(
            f"OpenRouter had a server error (HTTP {status}). Please try again.",
            transient=True,
        )
    return ProviderError(f"OpenRouter error: {detail}")
