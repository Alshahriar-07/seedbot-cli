"""Data-inspection commands: /history, /config."""

from __future__ import annotations

from rich.table import Table

from ..memory import list_sessions
from . import CommandContext, CommandResult, command


@command("history", "List saved conversation sessions")
def _history(ctx: CommandContext, arg: str) -> CommandResult:
    sessions = list_sessions()
    if not sessions:
        ctx.ui.dim("No saved sessions yet.")
        return CommandResult()
    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.accent")
    table.add_column(style="seed.dim")
    for sid, count in sessions[:20]:
        table.add_row(sid, f"{count} messages")
    ctx.ui.panel(table, title="History")
    return CommandResult()


@command("config", "Show current configuration")
def _config(ctx: CommandContext, arg: str) -> CommandResult:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.dim", justify="right")
    table.add_column(style="seed.text")
    table.add_row("API Key", ctx.config.masked_key())
    table.add_row("Model", ctx.config.model)
    table.add_row("Provider", ctx.config.provider)
    table.add_row("Theme", ctx.config.theme)
    table.add_row("Username", ctx.config.username)
    table.add_row("Streaming", "on" if ctx.config.stream else "off")
    ctx.ui.panel(table, title="Configuration")
    return CommandResult()
