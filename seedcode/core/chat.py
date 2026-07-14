"""Chat engine: talks to OpenRouter through the OpenAI SDK.

OpenRouter is OpenAI-API compatible, so we reuse the official SDK (see
:mod:`seedcode.core.client`). Streaming is the default path and SDK exceptions
are translated into :class:`ChatError` so the UI never surfaces a raw traceback.
"""

from __future__ import annotations

from collections.abc import Iterator

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    RateLimitError,
)

from .client import build_client
from .models import AppConfig, Message
from .streaming import iter_stream

SYSTEM_PROMPT = (
    "You are Seed Code, a fast, minimal, developer-focused AI coding assistant. "
    "Be concise and professional. Prefer clear, correct code with short "
    "explanations. Use markdown fenced code blocks with language hints."
)


class ChatError(Exception):
    """Raised with a user-friendly message when a request cannot complete."""


class ChatEngine:
    """Stateful conversation manager backed by OpenRouter."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.messages: list[Message] = [Message(role="system", content=SYSTEM_PROMPT)]
        self._client = build_client(config)

    # --- history management ------------------------------------------------
    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        self.messages.append(Message(role="assistant", content=content))

    def reset(self) -> None:
        """Clear the conversation but keep the system prompt."""
        self.messages = [self.messages[0]]

    @property
    def transcript(self) -> list[Message]:
        return self.messages

    # --- requests ----------------------------------------------------------
    def stream_reply(self) -> Iterator[str]:
        """Yield response chunks for the current conversation.

        Translates SDK exceptions into :class:`ChatError` with friendly text so
        the UI never surfaces a raw traceback.
        """
        payload = [m.to_api() for m in self.messages]
        try:
            stream = self._client.chat.completions.create(
                model=self.config.model,
                messages=payload,
                stream=True,
            )
            yield from iter_stream(stream)
        except AuthenticationError as exc:
            raise ChatError(
                "Authentication failed. Your API key may be invalid — run /config."
            ) from exc
        except RateLimitError as exc:
            raise ChatError("Rate limited by OpenRouter. Please wait and try again.") from exc
        except APIConnectionError as exc:
            raise ChatError("Network error reaching OpenRouter. Check your connection.") from exc
        except APIError as exc:
            detail = getattr(exc, "message", str(exc)) or "Unknown API error."
            raise ChatError(f"OpenRouter error: {detail}") from exc
        except Exception as exc:  # last-resort guard: never crash the REPL
            raise ChatError(f"Unexpected error: {exc}") from exc
