"""Seed Code theme system.

Multiple named palettes share one branding contract: a primary tone, an
accent, dim/text/warning/error/success roles, and a cursor-row background
for the interactive selector. The default "seed" palette is the classic
Seed Green identity; every other theme keeps the same structure so all
components render correctly under any of them.

Both rendering stacks read from here:

* Rich  — :func:`rich_theme` builds a :class:`rich.theme.Theme` with the
  ``seed.*`` style names used across the app.
* prompt_toolkit — :func:`pt_style` builds the ``sel.*`` style classes used
  by the interactive components in :mod:`seedcode.ui.selector` and friends.

The active theme is module-level state set from config at startup and by
the theme picker; components query it at render time so a theme switch is
instant everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.styles import Style
from rich.theme import Theme


@dataclass(frozen=True)
class Palette:
    """One named colour palette (all values are hex strings)."""

    id: str
    label: str
    description: str
    primary: str
    accent: str
    text: str
    dim: str
    warning: str
    error: str
    success: str
    cursor_bg: str  # selector highlighted-row background


PALETTES: dict[str, Palette] = {
    p.id: p
    for p in (
        Palette(
            id="seed",
            label="Seed Green",
            description="The classic Seed Code identity",
            primary="#2ecc71",
            accent="#7bed9f",
            text="#ffffff",
            dim="#9e9e9e",
            warning="#f1c40f",
            error="#e74c3c",
            success="#2ecc71",
            cursor_bg="#1d3b2a",
        ),
        Palette(
            id="forest",
            label="Forest",
            description="Deep greens and moss",
            primary="#27ae60",
            accent="#a3e4b8",
            text="#e8f5e9",
            dim="#7d8f84",
            warning="#e6c229",
            error="#e74c3c",
            success="#27ae60",
            cursor_bg="#16301f",
        ),
        Palette(
            id="ocean",
            label="Ocean",
            description="Calm blues and cyan",
            primary="#3498db",
            accent="#7fd6f2",
            text="#eaf6fb",
            dim="#8496a3",
            warning="#f1c40f",
            error="#e74c3c",
            success="#2ecc71",
            cursor_bg="#14303f",
        ),
        Palette(
            id="dusk",
            label="Dusk",
            description="Violet evening tones",
            primary="#9b59b6",
            accent="#d2a8e0",
            text="#f5eefa",
            dim="#988fa3",
            warning="#f1c40f",
            error="#e74c3c",
            success="#2ecc71",
            cursor_bg="#2d1f38",
        ),
        Palette(
            id="ember",
            label="Ember",
            description="Warm amber and orange",
            primary="#e67e22",
            accent="#f5b971",
            text="#fdf3e7",
            dim="#a3937f",
            warning="#f1c40f",
            error="#e74c3c",
            success="#2ecc71",
            cursor_bg="#3a2712",
        ),
        Palette(
            id="mono",
            label="Monochrome",
            description="Plain white on black",
            primary="#ffffff",
            accent="#c8c8c8",
            text="#ffffff",
            dim="#808080",
            warning="#f1c40f",
            error="#e74c3c",
            success="#ffffff",
            cursor_bg="#333333",
        ),
    )
}

DEFAULT_THEME = "seed"

# Module-level active theme (set from config at startup, and live by the
# theme picker). Components read it at render time.
_active: str = DEFAULT_THEME


def set_active_theme(name: str) -> Palette:
    """Set the active theme (unknown names fall back to the default)."""
    global _active
    _active = name if name in PALETTES else DEFAULT_THEME
    return PALETTES[_active]


def active_theme_name() -> str:
    return _active


def active_palette() -> Palette:
    return PALETTES.get(_active, PALETTES[DEFAULT_THEME])


def rich_theme(name: str | None = None) -> Theme:
    """Rich theme with the ``seed.*`` styles used across the app."""
    p = PALETTES.get(name or _active, PALETTES[DEFAULT_THEME])
    return Theme(
        {
            "seed.primary": f"bold {p.primary}",
            "seed.accent": p.accent,
            "seed.text": p.text,
            "seed.dim": p.dim,
            "seed.warning": p.warning,
            "seed.error": f"bold {p.error}",
            "seed.success": p.success,
            "seed.prompt": f"bold {p.primary}",
            "seed.assistant": p.accent,
            "markdown.code": p.accent,
        }
    )


def pt_style(name: str | None = None) -> Style:
    """prompt_toolkit style with the ``sel.*`` classes the components use."""
    p = PALETTES.get(name or _active, PALETTES[DEFAULT_THEME])
    return Style.from_dict(
        {
            "prompt": f"bold {p.primary}",
            "sel.title": f"bold {p.primary}",
            "sel.breadcrumb": p.dim,
            "sel.breadcrumb.here": f"bold {p.accent}",
            "sel.searchlabel": f"bold {p.primary}",
            "sel.query": p.text,
            "sel.placeholder": f"italic {p.dim}",
            "sel.pointer": f"bold {p.primary}",
            "sel.cursorline": f"bg:{p.cursor_bg}",
            "sel.text": p.text,
            "sel.dim": p.dim,
            "sel.match": f"bold underline {p.accent}",
            "sel.group": f"bold {p.accent}",
            "sel.hint": p.dim,
            "sel.counter": p.dim,
            "sel.ok": p.success,
            "sel.warn": p.warning,
            "sel.err": f"bold {p.error}",
            "sel.off": p.dim,
            "sel.scroll": p.dim,
            "sel.swatch.primary": f"bg:{p.primary}",
            "sel.swatch.accent": f"bg:{p.accent}",
            "sel.swatch.dim": f"bg:{p.dim}",
        }
    )


# Backwards-compatible export: the classic Seed Green Rich theme.
SEED_THEME = rich_theme(DEFAULT_THEME)
