"""Progress primitives: themed spinners and step indicators.

Kept deliberately small — the heavy lifting is Rich's Live display, which
already does minimal-redraw updates. This module provides the branded
wrappers so every wait state looks the same.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text


@contextmanager
def spinner(console: Console, label: str = "Working") -> Iterator[None]:
    """A transient themed spinner around a blocking operation."""
    view = Spinner("dots", text=Text(f" {label}...", style="seed.accent"))
    with Live(view, console=console, refresh_per_second=12, transient=True):
        yield


class StepProgress:
    """Sequential step reporting: ⟳ while running, ✓/✗ when finished."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def start(self, label: str) -> None:
        self._console.print(Text(f"⟳ {label}...", style="seed.warning"))

    def done(self, label: str) -> None:
        self._console.print(Text(f"✓ {label}", style="seed.success"))

    def fail(self, label: str, reason: str = "") -> None:
        suffix = f" — {reason}" if reason else ""
        self._console.print(Text(f"✗ {label}{suffix}", style="seed.error"))
