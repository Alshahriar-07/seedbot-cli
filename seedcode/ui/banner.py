"""The Seed Code startup banner.

A single branded screen: centered ASCII logo, wordmark, tagline and credits,
followed by a divider. Every line is centered dynamically against the live
terminal width (no hardcoded padding), rendered once at startup with plain
Text — no panels, boxes or animation — so it displays identically in Windows
Terminal, PowerShell, CMD and the VS Code terminal.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from ..core.models import AppConfig

_LOGO_LINES = [
    r" ███████╗███████╗███████╗██████╗      ██████╗ ██████╗ ██████╗ ███████╗",
    r" ██╔════╝██╔════╝██╔════╝██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    r" ███████╗█████╗  █████╗  ██║  ██║    ██║     ██║   ██║██║  ██║█████╗ ",
    r" ╚════██║██╔══╝  ██╔══╝  ██║  ██║    ██║     ██║   ██║██║  ██║██╔══╝ ",
    r" ███████║███████╗███████╗██████╔╝    ╚██████╗╚██████╔╝██████╔╝███████╗",
    r" ╚══════╝╚══════╝╚══════╝╚═════╝      ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

# Pure-ASCII fallback for legacy Windows consoles (raster-font cmd.exe)
# where the block/box-drawing glyphs above render as garbage.
_LOGO_LINES_ASCII = [
    r"  ____  _____ _____ ____     ____ ___  ____  _____ ",
    r" / ___|| ____| ____|  _ \   / ___/ _ \|  _ \| ____|",
    r" \___ \|  _| |  _| | | | | | |  | | | | | | |  _|  ",
    r"  ___) | |___| |___| |_| | | |__| |_| | |_| | |___ ",
    r" |____/|_____|_____|____/   \____\___/|____/|_____|",
]

# Monochrome green identity: bright bold logo, dimmer green for everything else.
_LOGO_STYLE = "bold #2ecc71"
_SOFT_STYLE = "#1cbf63"
_DIM_STYLE = "#159a4f"

_WORDMARK = "S E E D   C O D E"
_TAGLINE = "Plant ideas. Grow code."
_CREDIT_HEADING = "Created by"
_CREDIT_NAME = "Al Shahriar Sowan"
_CREDIT_TOOLS = "Vibe coded with GPT-5.5 + Claude Opus 4.8"


def _centered(console: Console, text: str, style: str) -> None:
    """Print one line centered against the current terminal width."""
    pad = max((console.size.width - len(text)) // 2, 0)
    line = Text(" " * pad + text, style=style)
    line.no_wrap = True
    console.print(line, overflow="crop")


def render_banner(console: Console, config: AppConfig) -> None:
    """Render the branded startup banner to ``console``."""
    logo = _LOGO_LINES_ASCII if console.legacy_windows else _LOGO_LINES
    console.print()
    for line in logo:
        _centered(console, line, _LOGO_STYLE)

    console.print()
    _centered(console, _WORDMARK, _LOGO_STYLE)
    console.print()
    _centered(console, _TAGLINE, _SOFT_STYLE)
    console.print()
    _centered(console, _CREDIT_HEADING, _DIM_STYLE)
    _centered(console, _CREDIT_NAME, _SOFT_STYLE)
    console.print()
    _centered(console, _CREDIT_TOOLS, _DIM_STYLE)

    console.print()
    divider_char = "-" if console.legacy_windows else "─"
    divider = Text(divider_char * console.size.width, style=_DIM_STYLE)
    divider.no_wrap = True
    console.print(divider, overflow="crop")
    console.print()