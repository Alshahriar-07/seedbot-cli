"""Core logic: data models, provider backends, chat engine, streaming."""

from __future__ import annotations

from .chat import ChatEngine, ChatError
from .models import AppConfig, Message
from .providers import (
    PROVIDERS,
    ModelInfo,
    Provider,
    ProviderError,
    ValidationResult,
    get_provider,
    provider_label,
)
from .streaming import iter_stream

__all__ = [
    "AppConfig",
    "ChatEngine",
    "ChatError",
    "Message",
    "ModelInfo",
    "PROVIDERS",
    "Provider",
    "ProviderError",
    "ValidationResult",
    "get_provider",
    "iter_stream",
    "provider_label",
]
