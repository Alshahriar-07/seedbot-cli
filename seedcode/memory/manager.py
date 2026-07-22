"""Management of the saved-session collection: listing saved transcripts.

Where :mod:`seedcode.memory.storage` persists a single live session, this
module reads back across all saved sessions on disk (used by /history).
"""

from __future__ import annotations

import json

from ..utils.helpers import history_dir


def list_sessions(provider_id: str = "") -> list[tuple[str, int]]:
    """Return ``(session_id, message_count)`` for saved sessions, newest first.

    With ``provider_id``, only that provider's own history is listed.
    """
    sessions: list[tuple[str, int]] = []
    for path in sorted(history_dir(provider_id).glob("session-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = path.stem.replace("session-", "")
            sessions.append((sid, len(data)))
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def load_session(provider_id: str, session_id: str) -> list[dict]:
    """Load one saved transcript as raw message dicts ([] on any failure)."""
    path = history_dir(provider_id) / f"session-{session_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def delete_session(provider_id: str, session_id: str) -> bool:
    """Delete one saved transcript; True when the file is gone afterwards."""
    path = history_dir(provider_id) / f"session-{session_id}.json"
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False
