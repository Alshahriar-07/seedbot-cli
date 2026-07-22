"""Search boxes: fuzzy pickers over large collections.

Thin task-specific wrappers around the Selector:

* :func:`search_list` — fuzzy-pick a value from any list of strings.
* :func:`search_files` — the Ctrl+P project file search (walks the
  workspace lazily, skips noise directories, caps the walk so huge repos
  stay instant).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from .selector import Option, select

# Directories that add noise, not results (mirrors core.project's skip list).
_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    ".tox", ".eggs",
}
_MAX_FILES = 5000


def search_list(
    values: Sequence[str],
    *,
    title: str = "",
    hint: str = "",
) -> str | None:
    """Fuzzy-pick one string from ``values``; None when cancelled."""
    return select(
        [Option(v) for v in values],
        title=title,
        hint=hint,
        max_rows=14,
    )


def project_files(root: Path | None = None, limit: int = _MAX_FILES) -> list[str]:
    """Collect project-relative file paths, skipping noise directories."""
    base = root or Path.cwd()
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        )
        rel_dir = os.path.relpath(dirpath, base)
        for name in sorted(filenames):
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            found.append(rel.replace(os.sep, "/"))
            if len(found) >= limit:
                return found
    return found


def search_files(root: Path | None = None) -> str | None:
    """Ctrl+P — fuzzy project file search; returns the chosen relative path."""
    files = project_files(root)
    if not files:
        return None
    return select(
        [Option(f) for f in files],
        title="Search Project Files",
        hint="type to filter   ↑↓ move   Enter open   Esc cancel",
        max_rows=14,
    )
