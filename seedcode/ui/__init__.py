"""Rich-based presentation layer for Seed Code.

Everything the user sees on screen is produced here so the visual identity —
the "Seed Green" theme, the ASCII banner, panels and spinners — stays in one
place. Business logic lives elsewhere and calls into these helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from ..core.models import AppConfig
from .banner import render_banner
from .renderer import StreamRenderer
from .theme import SEED_THEME

__all__ = ["UI", "StreamRenderer", "SEED_THEME"]


class UI:
    """Thin wrapper around a Rich console with Seed Code styling helpers."""

    def __init__(self) -> None:
        self.console = Console(theme=SEED_THEME, highlight=False)

    # --- primitives --------------------------------------------------------
    def print(self, *args, **kwargs) -> None:
        self.console.print(*args, **kwargs)

    def blank(self) -> None:
        self.console.print()

    def rule(self) -> None:
        self.console.rule(style="seed.dim")

    # --- startup -----------------------------------------------------------
    def banner(self, config: AppConfig) -> None:
        """Render the ASCII logo, tagline and status header."""
        render_banner(self.console, config)

    # --- chat rendering ----------------------------------------------------
    def user_prompt_label(self, username: str) -> str:
        """Prompt Toolkit consumes this via a formatted-text callable elsewhere."""
        return f"{username} > "

    def assistant_markdown(self, text: str) -> None:
        """Render a completed assistant message as markdown."""
        self.console.print(Markdown(text, code_theme="ansi_dark"))
        self.console.print()

    @contextmanager
    def thinking(self, label: str = "Thinking") -> Iterator[None]:
        """Show a spinner while awaiting the first streamed token."""
        spinner = Spinner("dots", text=Text(f" {label}...", style="seed.accent"))
        with Live(spinner, console=self.console, refresh_per_second=12, transient=True):
            yield

    @contextmanager
    def streaming(self) -> Iterator["StreamRenderer"]:
        """Provide a live, incrementally-updating markdown renderer."""
        renderer = StreamRenderer(self.console)
        with Live(
            renderer.renderable(),
            console=self.console,
            refresh_per_second=15,
            transient=False,
        ) as live:
            renderer.bind(live)
            yield renderer
        self.console.print()

    # --- messaging ---------------------------------------------------------
    def info(self, message: str) -> None:
        self.console.print(Text(message, style="seed.text"))

    def dim(self, message: str) -> None:
        self.console.print(Text(message, style="seed.dim"))

    def success(self, message: str) -> None:
        self.console.print(Text(f"✔ {message}", style="seed.success"))

    def warning(self, message: str) -> None:
        self.console.print(Text(f"! {message}", style="seed.warning"))

    def error(self, message: str) -> None:
        self.console.print(Text(f"✖ {message}", style="seed.error"))

    def panel(self, body, title: str | None = None) -> None:
        self.console.print(
            Panel(
                body,
                title=title,
                border_style="seed.primary",
                title_align="left",
                padding=(1, 2),
            )
        )
