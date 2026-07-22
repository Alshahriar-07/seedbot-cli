"""Small shared helpers for Seed Code.

Kept dependency-light so importing this module stays cheap during startup.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path


def app_dir() -> Path:
    """Return the per-user Seed Code directory, creating it if needed.

    Uses ``~/.seedcode`` on every platform for predictable, cross-platform
    behaviour (Windows PowerShell, Linux, macOS). If the home directory is
    unwritable (locked-down corporate machines), falls back to a temp
    location so the app still starts.
    """
    path = Path.home() / ".seedcode"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(tempfile.gettempdir()) / "seedcode"
        path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Path to the JSON configuration file."""
    return app_dir() / "config.json"


def history_dir(provider_id: str = "") -> Path:
    """Directory holding saved conversation transcripts.

    Each provider keeps its own history under ``history/<provider_id>/`` so
    switching backends never mixes conversations.
    """
    path = app_dir() / "history"
    if provider_id:
        path = path / provider_id
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # history is best-effort; callers already tolerate write failures
    return path


def restrict_permissions(path: Path) -> None:
    """Best-effort: make a file readable/writable by the owner only.

    On Windows this is a no-op (POSIX perms are ignored) but it never raises,
    so callers can invoke it unconditionally.
    """
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def session_id() -> str:
    """Generate a filesystem-safe id for a chat session."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())
