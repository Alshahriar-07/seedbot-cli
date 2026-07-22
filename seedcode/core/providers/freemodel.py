"""FreeModel backends: two independent providers sharing one FreeModel key.

FreeModel (https://freemodel.dev) runs TWO separate services, and Seed Code
exposes each as its own first-class provider — own base URL, own catalogue,
own connection status, own selected model:

* **FreeModel Claude** (``freemodel_claude``) — Claude-compatible (Anthropic
  Messages) API at ``https://cc.freemodel.dev``.
* **FreeModel Codex** (``freemodel_codex``) — OpenAI-compatible (Responses)
  API at ``https://api.freemodel.dev``.

Both authenticate with the user's FreeModel API key (``fe_oa_...`` from
https://freemodel.dev/dashboard); the key is stored per provider so either
can be replaced independently. Model catalogues are fetched live; the Claude
backend additionally keeps a maintained fallback list of the current Claude
family for when discovery is unavailable. Keys are validated ONLY by a real
authenticated request — never by format heuristics.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
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

_log = get_logger("freemodel")

# Codex backend: OpenAI-compatible API (Responses, with chat fallback).
CODEX_BASE = "https://api.freemodel.dev"
_CODEX_API = f"{CODEX_BASE}/v1"
_CODEX_MODELS_URL = f"{_CODEX_API}/models"

# Claude backend: Anthropic-Messages-compatible API.
CLAUDE_BASE = "https://cc.freemodel.dev"
_CLAUDE_MODELS_URL = f"{CLAUDE_BASE}/v1/models"
_CLAUDE_MESSAGES_URL = f"{CLAUDE_BASE}/v1/messages"
_CLAUDE_API_VERSION = "2023-06-01"

_TIMEOUT = 20.0
# Chat: fail fast on connect, but give busy free models time to answer.
_CHAT_TIMEOUT = httpx.Timeout(20.0, read=180.0)

# Sentinel model id for Auto mode (resolved per request, never sent as-is).
AUTO_MODEL = "auto"

# Maintained fallback for the Claude backend when catalogue discovery is
# unavailable: the current Claude family (aliases, newest first per tier).
CLAUDE_FALLBACK_MODELS: tuple[tuple[str, str], ...] = (
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-opus-4-7", "Claude Opus 4.7"),
    ("claude-opus-4-6", "Claude Opus 4.6"),
    ("claude-opus-4-5", "Claude Opus 4.5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
)

# Live-catalogue cache for Auto resolution, PER PROVIDER: id -> (at, entries).
_CATALOGUE_TTL_S = 300.0
_catalogue: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _codex_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _claude_headers(api_key: str) -> dict[str, str]:
    headers = {"anthropic-version": _CLAUDE_API_VERSION, "content-type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _fetch_entries(label: str, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch one backend's live catalogue. Raises ProviderError."""
    try:
        response = httpx.get(url, headers=headers, timeout=_TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data", [])
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"Timed out fetching the {label} catalogue.", transient=True
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(
            f"Could not fetch the {label} catalogue. Check your connection.",
            transient=True,
        ) from exc
    entries = [e for e in data if e.get("id")]
    if not entries:
        raise ProviderError(f"{label} reports no models right now.")
    return entries


def _validate_by_request(label: str, request: "Callable[[], httpx.Response]") -> ValidationResult:
    """Key validation via a real authenticated request — never heuristics.

    ``request`` performs the lightweight authenticated call (a 1-token chat
    probe: the ``/v1/models`` catalogues on both FreeModel gateways are
    public, so only a chat request actually exercises the key). Failures
    surface the actual server response so the user sees what the backend
    said, not a guess.
    """
    try:
        response = request()
    except httpx.TimeoutException:
        return ValidationResult(False, f"{label} validation timed out. Check your connection.")
    except httpx.HTTPError as exc:
        return ValidationResult(False, f"Could not reach {label}: {exc}")
    if response.status_code < 400:
        return ValidationResult(True, f"API key verified with {label}.")
    detail = response.text.strip()[:200] or response.reason_phrase
    return ValidationResult(
        False, f"{label} rejected the request (HTTP {response.status_code}): {detail}"
    )


class _FreeModelBase(Provider):
    """Shared plumbing for the two FreeModel providers (never registered)."""

    def _cached_entries(self, api_key: str) -> list[dict[str, Any]]:
        """Catalogue with a short per-provider cache for Auto mode."""
        now = time.monotonic()
        cached = _catalogue.get(self.id)
        if cached is not None and now - cached[0] < _CATALOGUE_TTL_S:
            return cached[1]
        entries = self._fetch(api_key)
        _catalogue[self.id] = (now, entries)
        return entries

    def _resolve_auto(self, api_key: str) -> str:
        """Pick the best model from this provider's live list."""
        entries = self._cached_entries(api_key)
        best = max(entries, key=lambda e: e.get("context_length") or 0)
        _log.info("auto mode (%s) resolved to %s", self.id, best["id"])
        return best["id"]

    def _fetch(self, api_key: str) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class FreeModelClaudeProvider(_FreeModelBase):
    """FreeModel's Claude-compatible backend at cc.freemodel.dev."""

    def __post_init__(self) -> None:
        self.id = "freemodel_claude"
        self.label = "FreeModel Claude"
        self.base_url = CLAUDE_BASE
        self.backend_label = "Claude API"
        self.requires_key = True
        self.supports_auto = True
        self.key_hint = "fe_oa_...  (get a free API key: https://freemodel.dev/dashboard)"

    def validate_key(self, api_key: str) -> ValidationResult:
        key = api_key.strip()
        if not key:
            return ValidationResult(False, "API key is empty.")

        def probe() -> httpx.Response:
            # A 1-token Messages request is the lightest call that actually
            # exercises the key (the catalogue endpoint is public).
            return httpx.post(
                _CLAUDE_MESSAGES_URL,
                headers=_claude_headers(key),
                json={
                    "model": self._probe_model(key),
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=_TIMEOUT,
            )

        return _validate_by_request(self.label, probe)

    def _probe_model(self, api_key: str) -> str:
        """A currently-served model id for the validation probe."""
        try:
            return self._cached_entries(api_key)[0]["id"]
        except ProviderError:
            return CLAUDE_FALLBACK_MODELS[0][0]

    def _fetch(self, api_key: str) -> list[dict[str, Any]]:
        return _fetch_entries(self.label, _CLAUDE_MODELS_URL, _claude_headers(api_key))

    def list_models(self, config: "AppConfig") -> list[ModelInfo]:
        """Live Claude catalogue, falling back to the maintained family list.

        Discovery failures (endpoint missing, timeout, bad payload) fall back
        so Claude models are ALWAYS selectable; the fallback is marked so the
        user knows the ids were not fetched live.
        """
        try:
            entries = self._fetch(config.get_api_key(self.id))
        except ProviderError as exc:
            _log.warning("claude catalogue unavailable (%s); using fallback list", exc)
            return [
                ModelInfo(id=model_id, label=label, detail="claude · fallback list")
                for model_id, label in CLAUDE_FALLBACK_MODELS
            ]
        models = []
        for entry in entries:
            ctx = entry.get("context_length")
            models.append(
                ModelInfo(
                    id=entry["id"],
                    label=entry.get("display_name") or entry.get("name") or entry["id"],
                    detail=f"claude · {ctx} ctx" if ctx else "claude",
                    is_free=True,
                )
            )
        models.sort(key=lambda m: m.id)
        return models

    def stream_chat(self, config: "AppConfig", messages: list["Message"]) -> Iterator[str]:
        api_key = config.get_api_key(self.id)
        model = config.model
        if model == AUTO_MODEL:
            model = self._resolve_auto(api_key)
        max_tokens = config.effective_max_tokens()
        _log.debug("claude chat request: model=%s max_tokens=%d", model, max_tokens)

        system = next((m.content for m in messages if m.role == "system"), None)
        turns = [m.to_api() for m in messages if m.role != "system"]
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": turns,
            "stream": True,
        }
        if system:
            payload["system"] = system
        try:
            with httpx.stream(
                "POST",
                _CLAUDE_MESSAGES_URL,
                headers=_claude_headers(api_key),
                json=payload,
                timeout=_CHAT_TIMEOUT,
            ) as response:
                self._raise_for_stream_status(response, model)
                # Anthropic-style SSE: data lines with typed JSON events.
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue  # tolerate keep-alive noise
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]
                    elif event.get("type") == "error":
                        message = (event.get("error") or {}).get(
                            "message", "Unknown FreeModel Claude error."
                        )
                        raise ProviderError(f"FreeModel Claude error: {message}")
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The FreeModel Claude request timed out. Please try again.", transient=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Network error reaching FreeModel Claude. Check your connection.",
                transient=True,
            ) from exc

    def _raise_for_stream_status(self, response: httpx.Response, model: str) -> None:
        status = response.status_code
        if status < 400:
            return
        if status in (401, 403):
            raise ProviderError(
                "Authentication failed. Your FreeModel key may be invalid — run /apikey."
            )
        if status == 404:
            raise ProviderError(
                f"Model '{model}' was not found on FreeModel Claude. "
                "Pick another with /model."
            )
        if status in (408, 429) or status >= 500:
            raise ProviderError(
                f"FreeModel Claude is unavailable right now (HTTP {status}). "
                "Please try again.",
                transient=True,
            )
        detail = response.read().decode("utf-8", "replace")[:300]
        raise ProviderError(f"FreeModel Claude error (HTTP {status}): {detail}")

    # --- native tool calling -------------------------------------------------
    def supports_tools(self, config: "AppConfig") -> bool:
        """The Claude family takes native tool definitions."""
        return True

    def stream_chat_with_tools(
        self, config: "AppConfig", messages: list["Message"], tools: list[ToolSpec]
    ) -> Iterator[StreamEvent]:
        api_key = config.get_api_key(self.id)
        model = config.model
        if model == AUTO_MODEL:
            model = self._resolve_auto(api_key)
        max_tokens = config.effective_max_tokens()
        _log.debug(
            "claude tool chat request: model=%s max_tokens=%d tools=%d",
            model, max_tokens, len(tools),
        )

        system = next((m.content for m in messages if m.role == "system"), None)
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_claude_turns(messages),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ],
            "stream": True,
        }
        if system:
            payload["system"] = system
        try:
            with httpx.stream(
                "POST",
                _CLAUDE_MESSAGES_URL,
                headers=_claude_headers(api_key),
                json=payload,
                timeout=_CHAT_TIMEOUT,
            ) as response:
                self._raise_for_stream_status(response, model)
                yield from _iter_claude_events(response)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The FreeModel Claude request timed out. Please try again.", transient=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Network error reaching FreeModel Claude. Check your connection.",
                transient=True,
            ) from exc


@dataclass
class FreeModelCodexProvider(_FreeModelBase):
    """FreeModel's OpenAI-compatible backend at api.freemodel.dev.

    Chat uses the Responses API first and transparently falls back to Chat
    Completions when the gateway does not expose ``/v1/responses`` (both are
    OpenAI-compatible surfaces of the same backend).
    """

    # Private client cache (key -> client); never shared with other providers.
    _client: Any = field(init=False, default=None, repr=False)
    _client_key: str = field(init=False, default="", repr=False)
    # Remembered per session after the first 404 so we don't re-probe.
    _use_chat_completions: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        self.id = "freemodel_codex"
        self.label = "FreeModel Codex"
        self.base_url = CODEX_BASE
        self.backend_label = "Responses API"
        self.requires_key = True
        self.supports_auto = True
        self.key_hint = "fe_oa_...  (get a free API key: https://freemodel.dev/dashboard)"

    def validate_key(self, api_key: str) -> ValidationResult:
        key = api_key.strip()
        if not key:
            return ValidationResult(False, "API key is empty.")
        try:
            model = self._probe_model(key)
        except ProviderError as exc:
            return ValidationResult(False, str(exc))

        def probe() -> httpx.Response:
            # A 1-token completion is the lightest call that actually
            # exercises the key (the catalogue endpoint is public).
            return httpx.post(
                f"{_CODEX_API}/chat/completions",
                headers=_codex_headers(key),
                json={
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=_TIMEOUT,
            )

        return _validate_by_request(self.label, probe)

    def _probe_model(self, api_key: str) -> str:
        """A currently-served model id for the validation probe."""
        entries = self._cached_entries(api_key)  # raises ProviderError offline
        return entries[0]["id"]

    def _fetch(self, api_key: str) -> list[dict[str, Any]]:
        return _fetch_entries(self.label, _CODEX_MODELS_URL, _codex_headers(api_key))

    def list_models(self, config: "AppConfig") -> list[ModelInfo]:
        entries = self._fetch(config.get_api_key(self.id))
        models = []
        for entry in entries:
            ctx = entry.get("context_length")
            models.append(
                ModelInfo(
                    id=entry["id"],
                    label=entry.get("display_name") or entry.get("name") or entry["id"],
                    detail=f"codex · {ctx} ctx" if ctx else "codex",
                    is_free=True,
                )
            )
        models.sort(key=lambda m: m.id)
        return models

    def _get_client(self, api_key: str):
        # The OpenAI SDK is the heaviest import in the app; loading it here
        # (first message) instead of at startup keeps launch fast.
        from openai import OpenAI

        if self._client is None or self._client_key != api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=_CODEX_API,
                timeout=_CHAT_TIMEOUT,
                # The engine owns retry policy; keep the SDK from stacking its own.
                max_retries=0,
            )
            self._client_key = api_key
        return self._client

    def stream_chat(self, config: "AppConfig", messages: list["Message"]) -> Iterator[str]:
        api_key = config.get_api_key(self.id)
        model = config.model
        if model == AUTO_MODEL:
            model = self._resolve_auto(api_key)
        max_tokens = config.effective_max_tokens()
        _log.debug("codex chat request: model=%s max_tokens=%d", model, max_tokens)

        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            NotFoundError,
            RateLimitError,
        )

        client = self._get_client(api_key)
        try:
            if not self._use_chat_completions:
                try:
                    yield from self._stream_responses(client, model, max_tokens, messages)
                    return
                except NotFoundError:
                    # /v1/responses not exposed by the gateway — remember and
                    # fall back to the Chat Completions surface.
                    _log.info("responses endpoint unavailable; using chat completions")
                    self._use_chat_completions = True
            yield from self._stream_chat_completions(client, model, max_tokens, messages)
        except AuthenticationError as exc:
            raise ProviderError(
                "Authentication failed. Your FreeModel key may be invalid — run /apikey."
            ) from exc
        except RateLimitError as exc:
            raise ProviderError(
                "Rate limited by FreeModel Codex. Please wait and try again.",
                transient=True,
            ) from exc
        except APITimeoutError as exc:
            raise ProviderError(
                "The FreeModel Codex request timed out. Please try again.", transient=True
            ) from exc
        except APIConnectionError as exc:
            # DNS failures, SSL errors, and dropped connections all land here.
            raise ProviderError(
                "Network error reaching FreeModel Codex. Check your connection.",
                transient=True,
            ) from exc
        except APIError as exc:
            raise _friendly_api_error(exc, model) from exc

    def _stream_responses(self, client, model, max_tokens, messages) -> Iterator[str]:
        """Primary path: the Responses API (/v1/responses)."""
        system = next((m.content for m in messages if m.role == "system"), None)
        turns = [m.to_api() for m in messages if m.role != "system"]
        kwargs: dict[str, Any] = {
            "model": model,
            "input": turns,
            "max_output_tokens": max_tokens,
            "stream": True,
        }
        if system:
            kwargs["instructions"] = system
        stream = client.responses.create(**kwargs)
        for event in stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                piece = getattr(event, "delta", "")
                if piece:
                    yield piece
            elif kind in ("response.failed", "error"):
                detail = getattr(getattr(event, "response", None), "error", None)
                message = getattr(detail, "message", None) or "Unknown FreeModel Codex error."
                raise ProviderError(f"FreeModel Codex error: {message}")

    def _stream_chat_completions(self, client, model, max_tokens, messages) -> Iterator[str]:
        """Fallback path: OpenAI Chat Completions (/v1/chat/completions)."""
        stream = client.chat.completions.create(
            model=model,
            messages=[m.to_api() for m in messages],  # type: ignore[arg-type]
            max_tokens=max_tokens,
            stream=True,
        )
        yield from iter_stream(stream)

    # --- native tool calling -------------------------------------------------
    def supports_tools(self, config: "AppConfig") -> bool:
        """Both OpenAI surfaces (Responses / Chat Completions) take tools."""
        return True

    def stream_chat_with_tools(
        self, config: "AppConfig", messages: list["Message"], tools: list[ToolSpec]
    ) -> Iterator[StreamEvent]:
        api_key = config.get_api_key(self.id)
        model = config.model
        if model == AUTO_MODEL:
            model = self._resolve_auto(api_key)
        max_tokens = config.effective_max_tokens()
        _log.debug(
            "codex tool chat request: model=%s max_tokens=%d tools=%d",
            model, max_tokens, len(tools),
        )

        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            NotFoundError,
            RateLimitError,
        )

        client = self._get_client(api_key)
        try:
            if not self._use_chat_completions:
                try:
                    yield from self._stream_responses_tools(
                        client, model, max_tokens, messages, tools
                    )
                    return
                except NotFoundError:
                    _log.info("responses endpoint unavailable; using chat completions")
                    self._use_chat_completions = True
            yield from self._stream_chat_completions_tools(
                client, model, max_tokens, messages, tools
            )
        except AuthenticationError as exc:
            raise ProviderError(
                "Authentication failed. Your FreeModel key may be invalid — run /apikey."
            ) from exc
        except RateLimitError as exc:
            raise ProviderError(
                "Rate limited by FreeModel Codex. Please wait and try again.",
                transient=True,
            ) from exc
        except APITimeoutError as exc:
            raise ProviderError(
                "The FreeModel Codex request timed out. Please try again.", transient=True
            ) from exc
        except APIConnectionError as exc:
            raise ProviderError(
                "Network error reaching FreeModel Codex. Check your connection.",
                transient=True,
            ) from exc
        except APIError as exc:
            raise _friendly_api_error(exc, model) from exc

    def _stream_responses_tools(
        self, client, model, max_tokens, messages, tools
    ) -> Iterator[StreamEvent]:
        """Responses API with tools: function_call output items stream in."""
        system = next((m.content for m in messages if m.role == "system"), None)
        kwargs: dict[str, Any] = {
            "model": model,
            "input": _to_responses_input(messages),
            "max_output_tokens": max_tokens,
            "tools": [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ],
            "stream": True,
        }
        if system:
            kwargs["instructions"] = system
        stream = client.responses.create(**kwargs)
        # call item id -> {call_id, name, args}
        pending: dict[str, dict[str, str]] = {}
        for event in stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                piece = getattr(event, "delta", "")
                if piece:
                    yield TextDelta(piece)
            elif kind == "response.output_item.added":
                item = getattr(event, "item", None)
                if getattr(item, "type", "") == "function_call":
                    pending[getattr(item, "id", "") or ""] = {
                        "call_id": getattr(item, "call_id", "") or "",
                        "name": getattr(item, "name", "") or "",
                        "args": getattr(item, "arguments", "") or "",
                    }
            elif kind == "response.function_call_arguments.delta":
                slot = pending.get(getattr(event, "item_id", "") or "")
                if slot is not None:
                    slot["args"] += getattr(event, "delta", "") or ""
            elif kind == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", "") == "function_call":
                    slot = pending.pop(getattr(item, "id", "") or "", None) or {
                        "call_id": getattr(item, "call_id", "") or "",
                        "name": getattr(item, "name", "") or "",
                        "args": "",
                    }
                    # The done item carries the full arguments; prefer them.
                    raw = (getattr(item, "arguments", "") or slot["args"]).strip() or "{}"
                    try:
                        arguments = json.loads(raw)
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be a JSON object")
                        yield ToolCallEvent(
                            id=slot["call_id"], name=slot["name"], arguments=arguments
                        )
                    except ValueError as exc:
                        yield ToolCallEvent(
                            id=slot["call_id"], name=slot["name"], arguments={},
                            error=f"Tool call arguments were not valid JSON: {exc}",
                        )
            elif kind in ("response.failed", "error"):
                detail = getattr(getattr(event, "response", None), "error", None)
                message = getattr(detail, "message", None) or "Unknown FreeModel Codex error."
                raise ProviderError(f"FreeModel Codex error: {message}")

    def _stream_chat_completions_tools(
        self, client, model, max_tokens, messages, tools
    ) -> Iterator[StreamEvent]:
        """Chat Completions with tools (OpenAI-style delta.tool_calls)."""
        stream = client.chat.completions.create(
            model=model,
            messages=[_to_openai_tools_message(m) for m in messages],  # type: ignore[arg-type]
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


def _to_claude_turns(messages: list["Message"]) -> list[dict[str, Any]]:
    """Serialize history to Anthropic Messages turns with tool blocks.

    Wire rules this must satisfy (the API 400s otherwise):
    * an assistant turn that called tools carries ``tool_use`` content blocks;
    * ALL of that turn's results arrive in the SINGLE next user message as
      ``tool_result`` blocks — consecutive role=="tool" messages are merged.
    """
    turns: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def flush_results() -> None:
        if pending_results:
            turns.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
            )
            continue
        flush_results()
        if message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content.strip():
                content.append({"type": "text", "text": message.content})
            content += [
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in message.tool_calls
            ]
            turns.append({"role": "assistant", "content": content})
        else:
            turns.append({"role": message.role, "content": message.content})
    flush_results()
    return turns


def _iter_claude_events(response: httpx.Response) -> Iterator[StreamEvent]:
    """Yield text deltas and COMPLETE tool calls from an Anthropic SSE stream.

    ``content_block_start`` with a ``tool_use`` block opens a call (id and
    name arrive there); ``input_json_delta`` fragments accumulate its
    argument JSON; ``content_block_stop`` closes and emits it.
    """
    open_calls: dict[int, dict[str, str]] = {}  # block index -> {id, name, json}
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue  # tolerate keep-alive noise
        kind = event.get("type")
        if kind == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                open_calls[event.get("index", 0)] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "json": "",
                }
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield TextDelta(delta["text"])
            elif delta.get("type") == "input_json_delta":
                slot = open_calls.get(event.get("index", 0))
                if slot is not None:
                    slot["json"] += delta.get("partial_json", "")
        elif kind == "content_block_stop":
            slot = open_calls.pop(event.get("index", 0), None)
            if slot is not None:
                raw = slot["json"].strip() or "{}"
                try:
                    arguments = json.loads(raw)
                    if not isinstance(arguments, dict):
                        raise ValueError("input must be a JSON object")
                    yield ToolCallEvent(
                        id=slot["id"], name=slot["name"], arguments=arguments
                    )
                except ValueError as exc:
                    yield ToolCallEvent(
                        id=slot["id"], name=slot["name"], arguments={},
                        error=f"Tool call arguments were not valid JSON: {exc}",
                    )
        elif kind == "error":
            message = (event.get("error") or {}).get(
                "message", "Unknown FreeModel Claude error."
            )
            raise ProviderError(f"FreeModel Claude error: {message}")


def _to_responses_input(messages: list["Message"]) -> list[dict[str, Any]]:
    """Serialize history to Responses API input items with function calls.

    Assistant tool calls become ``function_call`` items and results become
    ``function_call_output`` items, paired by ``call_id``.
    """
    items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            if message.content.strip():
                items.append({"role": "assistant", "content": message.content})
            items += [
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                }
                for call in message.tool_calls
            ]
            continue
        items.append({"role": message.role, "content": message.content})
    return items


def _to_openai_tools_message(message: "Message") -> dict[str, Any]:
    """OpenAI Chat Completions wire shape for a tool-calling conversation."""
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
    return message.to_api()


def _friendly_api_error(exc: Any, model: str) -> ProviderError:
    """Translate FreeModel Codex API errors into actionable user messages."""
    status = getattr(exc, "status_code", None)
    detail = getattr(exc, "message", str(exc)) or "Unknown API error."
    if status == 402:
        return ProviderError(
            "FreeModel Codex rejected the request (HTTP 402). Pick another model "
            "with /model, or lower max_tokens in /settings."
        )
    if status == 403:
        return ProviderError(
            "FreeModel Codex refused the request (HTTP 403). Your key may lack "
            "access to this model — pick another with /model."
        )
    if status == 404:
        return ProviderError(
            f"Model '{model}' was not found on FreeModel Codex. Pick another with /model."
        )
    if status == 408:
        return ProviderError(
            "FreeModel Codex timed out handling the request. Please try again.",
            transient=True,
        )
    if status is not None and status >= 500:
        return ProviderError(
            f"FreeModel Codex had a server error (HTTP {status}). Please try again.",
            transient=True,
        )
    return ProviderError(f"FreeModel Codex error: {detail}")
