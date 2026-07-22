"""Command palette (Ctrl+K) — searchable actions, VS Code style.

The palette is a fuzzy selector over registered actions, opened from the
chat prompt with Ctrl+K. Actions are plain (label, value) pairs supplied
by the app layer, so this module stays free of business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .selector import Option, select


@dataclass(slots=True)
class PaletteAction:
    """One palette entry: display label, returned value, optional detail."""

    label: str
    value: Any
    detail: str = ""
    group: str = ""


def command_palette(
    actions: Sequence[PaletteAction],
    *,
    title: str = "Command Palette",
) -> Any | None:
    """Open the palette; returns the chosen action's value or None."""
    return select(
        [
            Option(a.label, a.value, detail=a.detail, group=a.group)
            for a in actions
        ],
        title=title,
        hint="type to search   ↑↓ move   Enter run   Esc close",
        max_rows=12,
    )
