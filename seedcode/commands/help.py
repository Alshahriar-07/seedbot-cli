"""Informational commands: /help, /version, /shortcuts."""

from __future__ import annotations

from .. import __version__
from ..ui.layout import shortcuts_grid
from ..ui.selector import Option, select
from . import CommandContext, CommandResult, _REGISTRY, command

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+K", "Command Palette"),
    ("Ctrl+P", "Project File Search"),
    ("Ctrl+L", "Clear Screen"),
    ("Ctrl+R", "Search History"),
    ("Ctrl+/", "Keyboard Shortcuts"),
    ("Ctrl+,", "Settings"),
    ("Tab / Shift+Tab", "Next / Previous item"),
    ("↑ ↓", "Move selection"),
    ("Home / End", "Jump to first / last"),
    ("PageUp / PageDown", "Scroll a page"),
    ("Enter", "Confirm"),
    ("Esc", "Back / Cancel"),
    ("Ctrl+C", "Cancel current menu or response"),
)


def show_shortcuts(ui) -> None:
    """Render the keyboard-shortcut reference panel."""
    ui.panel(shortcuts_grid(SHORTCUTS), title="Keyboard Shortcuts")


@command("help", "Show available commands")
def _help(ctx: CommandContext, arg: str) -> CommandResult:
    # The command list itself is a searchable selector: Enter shows the
    # command's help line, Esc closes.
    options = [
        Option(f"/{name}", value=name, detail=help_text)
        for name, (_, help_text) in sorted(_REGISTRY.items())
    ]
    chosen = select(
        options,
        title="Commands",
        hint="type to filter   ↑↓ move   Esc close",
        max_rows=14,
    )
    if chosen is not None:
        _, help_text = _REGISTRY[str(chosen)]
        ctx.ui.info(f"/{chosen} — {help_text}")
    return CommandResult()


@command("shortcuts", "Show keyboard shortcuts", aliases=("keys",))
def _shortcuts(ctx: CommandContext, arg: str) -> CommandResult:
    show_shortcuts(ctx.ui)
    return CommandResult()


@command("version", "Show the Seed Code version")
def _version(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.ui.info(f"Seed Code v{__version__}")
    return CommandResult()
