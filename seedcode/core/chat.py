"""Chat engine: routes conversations through the active provider.

The engine owns conversation state and retry policy. Which vendor actually
answers is decided per request by ``config.provider`` + ``config.model``, so
switching providers or models mid-session takes effect on the next turn.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from .identity import build_system_prompt
from .models import AppConfig, Message
from .providers import ProviderError, get_provider, provider_label
from .providers.base import StreamEvent, ToolSpec
from ..utils.logger import get_logger

_log = get_logger("chat")

# Transparent retry for transient failures before any output has streamed.
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5


class ChatError(Exception):
    """Raised with a user-friendly message when a request cannot complete."""


class ChatEngine:
    """Stateful conversation manager delegating requests to providers."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        # Build identity-aware system prompt with current provider + model
        system_content = build_system_prompt(
            provider_label(config.provider), config.model or "unspecified"
        )
        self.messages: list[Message] = [Message(role="system", content=system_content)]

    # --- history management ------------------------------------------------
    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        self.messages.append(Message(role="assistant", content=content))

    def drop_last_user(self) -> None:
        """Remove a trailing unanswered user turn (after a failed request).

        Keeps the transcript alternating so the next attempt never sends two
        consecutive user messages, which strict APIs reject.
        """
        if self.messages and self.messages[-1].role == "user":
            self.messages.pop()

    def reset(self) -> None:
        """Clear the conversation but keep the system prompt."""
        self.messages = [self.messages[0]]

    @property
    def transcript(self) -> list[Message]:
        return self.messages

    # --- requests ----------------------------------------------------------
    def stream_reply(self) -> Iterator[str]:
        """Stream a reply via the current provider + current model.

        Transient provider failures are retried with a short backoff — but
        never once output has started, since a retry would replay the reply.
        All failures surface as :class:`ChatError` with friendly text.
        """
        provider = self._resolve_provider()
        yield from self._stream_with_retry(
            lambda: provider.stream_chat(self.config, self.messages)
        )

    def stream_reply_events(self, tools: list[ToolSpec]) -> Iterator[StreamEvent]:
        """Stream a reply as events (text deltas + native tool calls).

        Same retry policy as :meth:`stream_reply` — one shared helper owns
        it, so the two paths can never drift.
        """
        provider = self._resolve_provider()
        yield from self._stream_with_retry(
            lambda: provider.stream_chat_with_tools(self.config, self.messages, tools)
        )

    def _resolve_provider(self) -> Any:
        if not self.config.model:
            raise ChatError("No model selected. Pick one with /model first.")
        try:
            return get_provider(self.config.provider)
        except ProviderError as exc:
            raise ChatError(str(exc)) from exc

    def _stream_with_retry(self, request: Callable[[], Iterator[Any]]) -> Iterator[Any]:
        """Run a provider stream with transient retry before first output."""
        attempt = 0
        while True:
            yielded = False
            _log.info(
                "request: provider=%s model=%s turns=%d attempt=%d",
                self.config.provider,
                self.config.model,
                len(self.messages),
                attempt,
            )
            try:
                for piece in request():
                    yielded = True
                    yield piece
                _log.info("request complete: provider=%s", self.config.provider)
                return
            except ProviderError as exc:
                if exc.transient and not yielded and attempt < _MAX_RETRIES:
                    attempt += 1
                    _log.warning("transient failure, retry %d: %s", attempt, exc)
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                    continue
                _log.error("request failed: %s", exc)
                raise ChatError(str(exc)) from exc
            except ChatError:
                raise
            except Exception as exc:  # last-resort guard: never crash the REPL
                _log.exception("unexpected error during request")
                raise ChatError(f"Unexpected error: {exc}") from exc
