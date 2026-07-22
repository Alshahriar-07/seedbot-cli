"""Action menus built on the interactive Selector.

A menu is a selector over labelled actions: the main menu, the API-key
menu, and every "pick one of these things to do" screen use this instead
of numbered rows. Items may show a live status column and a badge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .selector import Option, select


@dataclass(slots=True)
class MenuItem:
    """One menu action: a label, the value returned when chosen, and an
    optional status column shown dimmed to the right."""

    label: str
    value: Any = None
    status: str = ""
    badge: str = ""
    group: str = ""
    disabled: bool = False

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = self.label


def run_menu(
    items: Sequence[MenuItem],
    *,
    title: str = "",
    breadcrumbs: Sequence[str] = (),
    hint: str = "",
    initial: Any = None,
    searchable: bool = True,
) -> Any | None:
    """Show an interactive menu; returns the chosen item's value or None."""
    options = [
        Option(
            label=item.label,
            value=item.value,
            columns=(item.status,) if item.status else (),
            badge=item.badge,
            group=item.group,
            disabled=item.disabled,
        )
        for item in items
    ]
    return select(
        options,
        title=title,
        breadcrumbs=breadcrumbs,
        hint=hint,
        initial=initial,
        searchable=searchable,
    )
