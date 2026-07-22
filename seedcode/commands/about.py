"""Meta commands: /about, /exit."""

from __future__ import annotations

from rich.text import Text

from .. import TAGLINE, __author__, __version__
from ..core.providers import provider_label
from . import CommandContext, CommandResult, command


def show_about(ui, config) -> None:
    """Render the About panel (shared by /about and the main menu)."""
    body = Text()
    body.append("Seed Code\n", style="seed.primary")
    body.append(f"{TAGLINE}\n\n", style="seed.accent")
    body.append(f"Version   {__version__}\n", style="seed.text")
    body.append(f"Author    {__author__}\n", style="seed.text")
    body.append(f"Provider  {provider_label(config.provider)}\n", style="seed.text")
    body.append(f"Model     {config.model or '(none)'}\n\n", style="seed.text")
    body.append("A premium terminal-based AI coding assistant.", style="seed.dim")
    ui.panel(body, title="About")


@command("about", "About Seed Code")
def _about(ctx: CommandContext, arg: str) -> CommandResult:
    show_about(ctx.ui, ctx.config)
    return CommandResult()


@command("exit", "Leave the chat (back to the main menu)", aliases=("quit", "q", "menu"))
def _exit(ctx: CommandContext, arg: str) -> CommandResult:
    ctx.ui.dim("Back to the menu.")
    return CommandResult(should_exit=True)
