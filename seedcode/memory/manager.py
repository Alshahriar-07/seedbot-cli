"""Management of the saved-session collection: listing and loading transcripts.

Where :mod:`seedcode.memory.storage` persists a single live session, this module
reads back across all saved sessions on disk.
"""

from __future__ import annotations

import json

from ..core.models import Message
from ..utils.helpers import history_dir


def list_sessions() -> list[tuple[str, int]]:
    """Return ``(session_id, message_count)`` for saved sessions, newest first."""
    sessions: list[tuple[str, int]] = []
    for path in sorted(history_dir().glob("session-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = path.stem.replace("session-", "")
            sessions.append((sid, len(data)))
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def load_session(sid: str) -> list[Message]:
    """Load a saved session by id, returning an empty list if unavailable."""
    path = history_dir() / f"session-{sid}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Message.model_validate(item) for item in data]
    except (json.JSONDecodeError, OSError, ValueError):
        return []
