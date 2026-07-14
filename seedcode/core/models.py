"""Pydantic data models for Seed Code.

All persisted and in-memory structured data flows through these models so that
validation happens in one place and the rest of the app can rely on typed data.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    """A single chat message in a conversation."""

    role: Role
    content: str
    timestamp: float = Field(default_factory=time.time)

    def to_api(self) -> dict[str, str]:
        """Return the minimal shape the OpenAI SDK expects."""
        return {"role": self.role, "content": self.content}


class AppConfig(BaseModel):
    """Persisted application configuration.

    Stored as JSON under the user's config directory. The API key lives here but
    the file is written with owner-only permissions where the OS supports it.
    """

    api_key: str = ""
    model: str = "z-ai/glm-5.2"
    provider: str = "OpenRouter"
    theme: str = "seed"
    username: str = "You"
    stream: bool = True

    def is_configured(self) -> bool:
        """True when a non-empty API key is present."""
        return bool(self.api_key.strip())

    def masked_key(self) -> str:
        """Return the API key with the middle obscured for safe display."""
        key = self.api_key.strip()
        if not key:
            return "(not set)"
        if len(key) <= 12:
            return "*" * len(key)
        return f"{key[:8]}...{key[-4:]}"
