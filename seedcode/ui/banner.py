"""The Seed Code ASCII banner and startup header."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .. import TAGLINE, __version__
from ..core.models import AppConfig

# Seed Green gradient applied line-by-line to the banner for depth.
_BANNER_LINES = [
    r"    ███████╗███████╗███████╗██████╗ ",
    r"    ██╔════╝██╔════╝██╔════╝██╔══██╗",
    r"    ███████╗█████╗  █████╗  ██║  ██║",
    r"    ╚════██║██╔══╝  ██╔══╝  ██║  ██║",
    r"    ███████║███████╗███████╗██████╔╝",
    r"    ╚══════╝╚══════╝╚══════╝╚═════╝ ",
]
_BANNER_SHADES = ["#0e6b3a", "#159a4f", "#1cbf63", "#2ecc71", "#57d98a", "#7bed9f"]


def render_banner(console: Console, config: AppConfig) -> None:
    """Render the ASCII logo, tagline and status header to ``console``."""
    console.print()
    for line, shade in zip(_BANNER_LINES, _BANNER_SHADES):
        console.print(Text(line, style=f"bold {shade}"))

    title = Text()
    title.append("             Seed Code ", style="seed.primary")
    title.append(f"v{__version__}", style="seed.dim")
    console.print(title)
    console.print(Text(f"        {TAGLINE}", style="seed.accent"))
    console.print()

    status = Table.grid(padding=(0, 2))
    status.add_column(style="seed.dim", justify="right")
    status.add_column(style="seed.text")
    status.add_row("Model", config.model)
    status.add_row("Provider", config.provider)
    status.add_row("Status", Text("● Ready", style="seed.success"))
    console.print(status)
    console.print()
    console.print(Text("Type /help for commands, /exit to quit.", style="seed.dim"))
    console.print()
