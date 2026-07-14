"""Seed Code colour system.

Primary: Seed Green.  Accent: Soft Green.  Text: white/gray.
Warning: yellow.  Error: red.  No neon, no rainbow.
"""

from __future__ import annotations

from rich.theme import Theme

SEED_THEME = Theme(
    {
        "seed.primary": "bold #2ecc71",
        "seed.accent": "#7bed9f",
        "seed.text": "white",
        "seed.dim": "grey62",
        "seed.warning": "yellow",
        "seed.error": "bold red",
        "seed.success": "#2ecc71",
        "seed.prompt": "bold #2ecc71",
        "seed.assistant": "#7bed9f",
        "markdown.code": "#7bed9f",
    }
)
