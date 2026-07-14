"""Meta commands: /about, /exit."""

from __future__ import annotations

from rich.text import Text

from .. import TAGLINE, __author__, __version__
from . import CommandContext, CommandResult, command


@command("about", "About Seed Code")
def _about(ctx: CommandContext, arg: str) -> CommandResult:
    body = Text()
    body.append("Seed Code\n", style="seed.primary")
    body.append(f"{TAGLINE}\n\n", style="seed.accent")
    body.append(f"Version   {__version__}\n", style="seed.text")
    body.append(f"Author    {__author__}\n", style="seed.text")
    body.append("Provider  OpenRouter\n\n", style="seed.text")
    body.append("A premium terminal-based AI coding assistant.", style="seed.dim")
    ctx.ui.panel(body, title="About")
    return CommandResult()


@command("exit", "Exit Seed Code", aliases=("quit", "q"))
def _exit(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.ui.dim("Goodbye — plant ideas, grow code.")
    return CommandResult(should_exit=True)
