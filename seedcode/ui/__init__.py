"""Rich-based presentation layer for Seed Code.

Everything the user sees on screen is produced here so the visual identity —
the Seed theme system, the startup dashboard, panels, spinners, and the
interactive component library (selector, menus, dialogs, palette) — stays in
one place. Business logic lives elsewhere and calls into these helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from ..core.models import AppConfig
from .dashboard import render_dashboard
from .renderer import StreamRenderer
from .theme import SEED_THEME, rich_theme, set_active_theme

__all__ = ["UI", "StreamRenderer", "SEED_THEME"]


class UI:
    """Thin wrapper around a Rich console with Seed Code styling helpers."""

    def __init__(self) -> None:
        self.console = Console(theme=rich_theme(), highlight=False)
        # The active Live display (spinner/stream), if any — permission
        # dialogs pause it so interactive input works cleanly.
        self._live: Live | None = None
        # Legacy Windows consoles (pre-Windows-Terminal cmd.exe with raster
        # fonts) can't render ✔/✖ — fall back to pure-ASCII markers there.
        if self.console.legacy_windows:
            self._ok_mark, self._err_mark = "[OK]", "[X]"
        else:
            self._ok_mark, self._err_mark = "✔", "✖"
        self._theme_pushed = False

    def apply_theme(self, name: str) -> None:
        """Switch the active theme everywhere (console + interactive styles).

        Keeps exactly one theme overlay on the console so live-preview
        arrowing through the picker never stacks themes.
        """
        set_active_theme(name)
        if self._theme_pushed:
            try:
                self.console.pop_theme()
            except Exception:
                pass
        self.console.push_theme(rich_theme(name))
        self._theme_pushed = True

    # --- primitives --------------------------------------------------------
    def print(self, *args, **kwargs) -> None:
        self.console.print(*args, **kwargs)

    def blank(self) -> None:
        self.console.print()

    # --- startup -----------------------------------------------------------
    def banner(self, config: AppConfig) -> None:
        """Render the startup dashboard (shown exactly once at launch)."""
        render_dashboard(self.console, config)

    # --- chat rendering ----------------------------------------------------
    @contextmanager
    def thinking(self, label: str = "Thinking") -> Iterator[None]:
        """Show a spinner while awaiting the first streamed token."""
        spinner = Spinner("dots", text=Text(f" {label}...", style="seed.accent"))
        with Live(
            spinner, console=self.console, refresh_per_second=12, transient=True
        ) as live:
            self._live = live
            try:
                yield
            finally:
                self._live = None

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
        self.console.print(Text(f"{self._ok_mark} {message}", style="seed.success"))

    def warning(self, message: str) -> None:
        self.console.print(Text(f"! {message}", style="seed.warning"))

    def error(self, message: str) -> None:
        self.console.print(Text(f"{self._err_mark} {message}", style="seed.error"))

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

    # --- action confirmation ------------------------------------------------
    def _confirm(self, title: str, category_label: str, description: str) -> str:
        """Ask the user to approve an action; returns 'y', 'a', or 'n'.

        Shows the action details in a warning panel, then an interactive
        Allow Once / Always Allow / Deny dialog. Pauses any live spinner so
        the dialog renders cleanly, then resumes it. Cancelling (Esc or
        Ctrl+C) counts as deny — never approve by accident.
        """
        from .dialog import permission_dialog

        live = self._live
        if live is not None:
            live.stop()
        try:
            body = Text()
            body.append(f"{category_label}\n", style="seed.warning")
            body.append(description, style="seed.text")
            self.console.print(
                Panel(
                    body,
                    title=title,
                    border_style="seed.warning",
                    title_align="left",
                    padding=(1, 2),
                )
            )
            return permission_dialog()
        finally:
            if live is not None:
                live.start()

    def confirm_desktop(self, category_label: str, description: str) -> str:
        """Approve a desktop action; returns 'y', 'a', or 'n'."""
        return self._confirm("Desktop Control", category_label, description)

    def confirm_tool_action(self, category_label: str, description: str) -> str:
        """Approve a dangerous agent tool action; returns 'y', 'a', or 'n'."""
        return self._confirm("Assist Action", category_label, description)
