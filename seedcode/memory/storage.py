"""Conversation history persistence.

Each session is stored as a JSON file under ``~/.seedcode/history``. History is
best-effort: failures to read or write are swallowed so a disk hiccup never
interrupts a chat.
"""

from __future__ import annotations

import json

from ..core.models import Message
from ..utils.helpers import history_dir, restrict_permissions, session_id


class HistoryStore:
    """Append-friendly JSON transcript for a single chat session.

    Transcripts are stored per provider (``history/<provider>/...``) so each
    backend keeps its own independent history.
    """

    def __init__(self, sid: str | None = None, provider_id: str = "") -> None:
        self.session_id = sid or session_id()
        self.provider_id = provider_id
        self.path = history_dir(provider_id) / f"session-{self.session_id}.json"

    def save(self, messages: list[Message]) -> None:
        """Write the full transcript (excluding system messages) to disk."""
        payload = [m.model_dump() for m in messages if m.role != "system"]
        try:
            self.path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            restrict_permissions(self.path)
        except OSError:
            # History is a convenience, never a hard requirement.
            pass
