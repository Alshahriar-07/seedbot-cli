"""Small shared helpers for Seed Code.

Kept dependency-light so importing this module stays cheap during startup.
"""

from __future__ import annotations

import time
from pathlib import Path


def app_dir() -> Path:
    """Return the per-user Seed Code directory, creating it if needed.

    Uses ``~/.seedcode`` on every platform for predictable, cross-platform
    behaviour (Windows PowerShell, Linux, macOS).
    """
    path = Path.home() / ".seedcode"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Path to the JSON configuration file."""
    return app_dir() / "config.json"


def history_dir() -> Path:
    """Directory holding saved conversation transcripts."""
    path = app_dir() / "history"
    path.mkdir(parents=True, exist_ok=True)
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


def human_timestamp(epoch: float | None = None) -> str:
    """Format an epoch time as a compact local timestamp."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def session_id() -> str:
    """Generate a filesystem-safe id for a chat session."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())
