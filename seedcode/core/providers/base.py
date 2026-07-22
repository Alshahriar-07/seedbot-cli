"""Provider abstraction: the contract every AI backend implements.

A provider is a fully independent backend: it owns its API key slot, base
URL, model catalogue, client, and connection status. The chat engine and the
UI never talk to a vendor API directly — they go through this interface, so
providers share ONLY the common chat contract, never each other's logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import AppConfig, Message


class ProviderError(Exception):
    """A provider request failed with a user-presentable message.

    ``transient`` marks failures worth retrying automatically (timeouts,
    connection drops, rate limits) as opposed to permanent ones (bad key,
    unknown model).
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(slots=True)
class ValidationResult:
    """Outcome of an API key validation attempt."""

    ok: bool
    message: str


@dataclass(slots=True)
class ModelInfo:
    """One selectable model as reported by a provider.

    ``is_free`` is set by providers whose catalogue carries pricing
    (True/False); ``None`` means pricing does not apply (e.g. local models).
    """

    id: str
    label: str = ""
    detail: str = ""
    is_free: bool | None = None

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.id


# Connection-status display values (session-only, never persisted).
STATUS_UNKNOWN = "Not Checked"
STATUS_CONNECTED = "Connected"
STATUS_OFFLINE = "Offline"
STATUS_NO_KEY = "No API Key"
STATUS_BAD_KEY = "Invalid Key"


# --- native tool calling ------------------------------------------------------
@dataclass(slots=True)
class ToolSpec:
    """Provider-neutral tool description.

    ``parameters`` is a JSON-schema object
    (``{"type": "object", "properties": {...}, "required": [...]}``); each
    provider converts it to its own wire format (OpenAI ``function``,
    Anthropic ``input_schema``, ...).
    """

    name: str
    description: str
    parameters: dict


@dataclass(slots=True)
class TextDelta:
    """A streamed piece of assistant text."""

    text: str


@dataclass(slots=True)
class ToolCallEvent:
    """One COMPLETE native tool call.

    Providers accumulate their own streamed argument fragments and emit a
    single event per finished call, so consumers never see wire-format
    details. When the accumulated argument JSON would not parse, ``error``
    carries the parse problem (and ``arguments`` is empty) — the agent feeds
    it back to the model like any other malformed call.
    """

    id: str
    name: str
    arguments: dict
    error: str = ""


StreamEvent = TextDelta | ToolCallEvent


@dataclass
class Provider(ABC):
    """Base class for AI backends.

    Each concrete provider sets its identity in ``__post_init__`` and keeps
    its own private client/catalogue caches — nothing is shared between
    provider modules.
    """

    id: str = field(init=False)
    label: str = field(init=False)
    base_url: str = field(init=False, default="")
    requires_key: bool = field(init=False, default=True)
    key_hint: str = field(init=False, default="")
    # Human name of the API family this backend speaks (e.g. "Claude API",
    # "Responses API"); shown on the dashboard. Empty means "<label> API".
    backend_label: str = field(init=False, default="")
    # True when the provider supports the 'auto' model sentinel (the best
    # model is resolved from the live catalogue per request).
    supports_auto: bool = field(init=False, default=False)
    # Last known connection status for this provider (session-only cache;
    # refreshed by :meth:`refresh_status` — reading it does no network I/O).
    status: str = field(init=False, default=STATUS_UNKNOWN)

    def prepare(self, config: "AppConfig") -> None:
        """Sync per-config state (e.g. an active sub-backend) before use.

        Called by shared flows (key entry, validation, doctor) so a provider
        with internal modes always acts on the configured one. Default: no-op.
        """

    def supports_images(self, config: "AppConfig") -> bool:
        """Whether this backend can accept image attachments on messages.

        Providers that can forward base64 screenshots to a vision-capable
        model override this; the default is text-only, and callers must not
        attach images when it returns False.
        """
        return False

    @abstractmethod
    def validate_key(self, api_key: str) -> ValidationResult:
        """Check credentials with a REAL API request (never heuristics).

        Providers without keys validate connectivity instead.
        """

    @abstractmethod
    def list_models(self, config: "AppConfig") -> list[ModelInfo]:
        """Fetch the models the user may select. Raises ProviderError."""

    @abstractmethod
    def stream_chat(self, config: "AppConfig", messages: list["Message"]) -> Iterator[str]:
        """Stream a reply for the conversation. Raises ProviderError."""

    # --- native tool calling -------------------------------------------------
    def supports_tools(self, config: "AppConfig") -> bool:
        """Whether this backend can take native tool/function definitions.

        When False, the agent talks to the model through the text protocol
        instead (fenced ``tool`` blocks). True is an *attempt*: a runtime
        failure still falls back gracefully at the agent layer.
        """
        return False

    def stream_chat_with_tools(
        self, config: "AppConfig", messages: list["Message"], tools: list[ToolSpec]
    ) -> Iterator[StreamEvent]:
        """Stream a reply as events: text deltas and complete tool calls.

        Default degrades to plain text so a provider without an override
        still works (through the text protocol). Raises ProviderError.
        """
        for piece in self.stream_chat(config, messages):
            yield TextDelta(piece)

    # --- connection status ---------------------------------------------------
    def refresh_status(self, config: "AppConfig") -> str:
        """Probe the backend with a real request and cache the outcome.

        Never raises; the result is stored in :attr:`status` and returned so
        the UI can refresh immediately after a provider switch.
        """
        try:
            if self.requires_key:
                key = config.get_api_key(self.id).strip()
                if not key:
                    self.status = STATUS_NO_KEY
                    return self.status
                result = self.validate_key(key)
                if result.ok:
                    self.status = STATUS_CONNECTED
                elif "connection" in result.message.lower() or "timed out" in result.message.lower():
                    self.status = STATUS_OFFLINE
                else:
                    self.status = STATUS_BAD_KEY
            else:
                self.status = STATUS_CONNECTED if self.detect(config) else STATUS_OFFLINE
        except Exception:  # a status probe must never break the UI
            self.status = STATUS_OFFLINE
        return self.status

    def detect(self, config: "AppConfig") -> bool:
        """Backend reachability for key-less providers (default: unknown)."""
        return False

    # --- provider-specific settings -------------------------------------------
    def extra_settings(self, config: "AppConfig") -> dict[str, str]:
        """Provider-specific settings shown on its own settings screen.

        Returns ``{setting name: current display value}``; empty when the
        provider has none. Values live in the provider's own config entry
        (``ProviderConfig.options``), never shared.
        """
        return {}

    def set_extra_setting(
        self, config: "AppConfig", name: str, value: str
    ) -> tuple[bool, str]:
        """Apply a provider-specific setting; returns (ok, user message)."""
        return False, f"{self.label} has no setting '{name}'."
