"""Informational commands: /help, /model, /version."""

from __future__ import annotations

from rich.table import Table

from .. import __version__
from ..config import save_config
from . import CommandContext, CommandResult, _REGISTRY, command


@command("help", "Show available commands")
def _help(ctx: CommandContext, arg: str) -> CommandResult:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.primary", no_wrap=True)
    table.add_column(style="seed.text")
    for name, (_, help_text) in sorted(_REGISTRY.items()):
        table.add_row(f"/{name}", help_text)
    ctx.ui.panel(table, title="Commands")
    return CommandResult()


@command("model", "Show or change the active model. Usage: /model [name]", aliases=("show",))
def _model(ctx: CommandContext, arg: str) -> CommandResult:
    target = arg.strip()
    # Support the documented "/show model" phrasing.
    if target.lower().startswith("model"):
        target = target[len("model"):].strip()
    if not target:
        ctx.ui.info(f"Current model: {ctx.config.model}")
        ctx.ui.dim(f"Provider: {ctx.config.provider}")
        return CommandResult()
    ctx.config.model = target
    save_config(ctx.config)
    ctx.ui.success(f"Model set to {target}")
    return CommandResult()


@command("version", "Show the Seed Code version")
def _version(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.ui.info(f"Seed Code v{__version__}")
    return CommandResult()
