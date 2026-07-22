"""/palette and /files — the command palette (Ctrl+K) and project search (Ctrl+P).

The palette lists every high-level action (Change Provider, Change Model,
Settings, History, Doctor, Clear History, About, Theme, Assist Mode, Search
Projects) as a fuzzy-searchable selector, VS Code style. The chat REPL
binds Ctrl+K / Ctrl+P to these commands so they open mid-conversation.
"""

from __future__ import annotations

from pathlib import Path

from ..ui.palette import PaletteAction, command_palette
from ..ui.searchbox import search_files
from . import CommandContext, CommandResult, command, dispatch


def _actions(ctx: CommandContext) -> list[PaletteAction]:
    assist_on = ctx.config.agent_mode
    return [
        PaletteAction("Change Provider", "/provider", detail="switch AI backend"),
        PaletteAction("Change Model", "/model", detail="browse the live catalogue"),
        PaletteAction("Settings", "/settings", detail="interactive settings"),
        PaletteAction("History", "/history", detail="browse saved sessions"),
        PaletteAction("Doctor", "/doctor", detail="diagnose configuration and network"),
        PaletteAction("Clear History", "__clear_history__",
                      detail="delete this provider's saved sessions"),
        PaletteAction("About", "/about", detail="version and credits"),
        PaletteAction("Theme", "/theme", detail="pick a colour theme (live preview)"),
        PaletteAction(
            "Assist Mode",
            f"/assist {'off' if assist_on else 'on'}",
            detail=f"currently {'on' if assist_on else 'off'}",
        ),
        PaletteAction("Search Projects", "__files__", detail="fuzzy project file search"),
        PaletteAction("Keyboard Shortcuts", "/shortcuts", detail="key reference"),
        PaletteAction("Clear Screen", "/clear", detail="wipe the terminal"),
    ]


def open_palette(ctx: CommandContext) -> CommandResult:
    """Open the command palette and run the chosen action."""
    chosen = command_palette(_actions(ctx))
    if chosen is None:
        return CommandResult()
    if chosen == "__files__":
        return open_file_search(ctx)
    if chosen == "__clear_history__":
        from ..memory import delete_session, list_sessions
        from ..ui.dialog import confirm_dialog

        sessions = list_sessions(ctx.config.provider)
        if not sessions:
            ctx.ui.dim("No saved sessions to clear.")
            return CommandResult()
        if confirm_dialog(
            f"Delete all {len(sessions)} saved sessions?",
            yes_label="Delete All",
            no_label="Keep",
            danger=True,
        ):
            removed = sum(
                1 for sid, _ in sessions if delete_session(ctx.config.provider, sid)
            )
            ctx.ui.success(f"Removed {removed} sessions.")
        return CommandResult()
    return dispatch(ctx, str(chosen))


def open_file_search(ctx: CommandContext) -> CommandResult:
    """Open the Ctrl+P project file search; show the chosen file."""
    chosen = search_files(Path.cwd())
    if chosen is None:
        return CommandResult()
    path = Path.cwd() / chosen
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        ctx.ui.error(f"Cannot open {chosen}: {exc}")
        return CommandResult()
    lines = text.splitlines()
    from rich.syntax import Syntax

    snippet = "\n".join(lines[:80])
    body = Syntax(snippet, Syntax.guess_lexer(str(path), snippet),
                  theme="ansi_dark", line_numbers=True)
    ctx.ui.panel(body, title=str(chosen))
    if len(lines) > 80:
        ctx.ui.dim(f"({len(lines) - 80} more lines — showing the first 80)")
    return CommandResult()


@command("palette", "Open the command palette (Ctrl+K)", aliases=("commands",))
def _palette(ctx: CommandContext, arg: str) -> CommandResult:
    return open_palette(ctx)


@command("files", "Search project files (Ctrl+P)", aliases=("search",))
def _files(ctx: CommandContext, arg: str) -> CommandResult:
    return open_file_search(ctx)
