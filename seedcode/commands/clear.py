"""Screen and context commands: /clear, /reset."""

from __future__ import annotations

from . import CommandContext, CommandResult, command


@command("clear", "Clear the screen")
def _clear(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.ui.console.clear()
    ctx.ui.banner(ctx.config)
    return CommandResult()


@command("reset", "Forget the current conversation context")
def _reset(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.engine.reset()  # type: ignore[attr-defined]
    ctx.ui.success("Conversation context cleared.")
    return CommandResult()
