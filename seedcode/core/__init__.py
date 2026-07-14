"""Core logic: data models, OpenRouter client, chat engine, streaming."""

from __future__ import annotations

from .chat import ChatEngine, ChatError, SYSTEM_PROMPT
from .client import ValidationResult, build_client, validate_key
from .models import AppConfig, Message
from .streaming import iter_stream

__all__ = [
    "AppConfig",
    "ChatEngine",
    "ChatError",
    "Message",
    "SYSTEM_PROMPT",
    "ValidationResult",
    "build_client",
    "iter_stream",
    "validate_key",
]
