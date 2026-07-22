"""Shared layout conventions: panels, key-value grids, shortcut tables.

Every screen builds its content through these helpers so padding, borders
and column styles stay identical across the app.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table


def branded_panel(body: RenderableType, title: str | None = None) -> Panel:
    """The standard Seed Code panel: primary border, left title, padding."""
    return Panel(
        body,
        title=title,
        border_style="seed.primary",
        title_align="left",
        padding=(1, 2),
    )


def kv_grid(rows: Iterable[tuple[str, RenderableType]]) -> Table:
    """A two-column label/value grid (labels dimmed right, values plain)."""
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="seed.dim", justify="right", no_wrap=True)
    grid.add_column(style="seed.text")
    for label, value in rows:
        grid.add_row(label, value)
    return grid


def columns_grid(rows: Sequence[Sequence[str]], styles: Sequence[str]) -> Table:
    """An n-column grid with one style per column."""
    grid = Table.grid(padding=(0, 2))
    for style in styles:
        grid.add_column(style=style)
    for row in rows:
        grid.add_row(*row)
    return grid


def shortcuts_grid(pairs: Sequence[tuple[str, str]]) -> Table:
    """Keyboard-shortcut table: accent keys, plain descriptions."""
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style="seed.accent", no_wrap=True)
    grid.add_column(style="seed.text")
    for key, action in pairs:
        grid.add_row(key, action)
    return grid
