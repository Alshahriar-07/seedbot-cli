"""Slash-command system for the Seed Code REPL.

Commands are registered in a table and dispatched by name. Each handler receives
the live :class:`CommandContext` and returns a :class:`CommandResult` telling the
REPL whether to keep looping or exit. Handlers live in the sibling modules
(:mod:`help`, :mod:`clear`, :mod:`history`, :mod:`about`) and are imported at the
bottom of this file so their ``@command`` decorators populate the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class CommandContext:
    """Everything a command handler might need to act on."""

    ui: "object"  # UI; typed loosely to avoid an import cycle.
    config: "object"  # AppConfig
    engine: "object"  # ChatEngine


@dataclass
class CommandResult:
    """Signals control flow back to the REPL."""

    should_exit: bool = False
    handled: bool = True


Handler = Callable[[CommandContext, str], CommandResult]

# name -> (handler, help text). Populated via the @command decorator below.
_REGISTRY: dict[str, tuple[Handler, str]] = {}
_ALIASES: dict[str, str] = {}


def command(
    name: str, help_text: str, aliases: tuple[str, ...] = ()
) -> Callable[[Handler], Handler]:
    def wrap(func: Handler) -> Handler:
        _REGISTRY[name] = (func, help_text)
        for alias in aliases:
            _ALIASES[alias] = name
        return func

    return wrap


def is_command(text: str) -> bool:
    return text.strip().startswith("/")


def dispatch(ctx: CommandContext, text: str) -> CommandResult:
    """Route ``text`` (a '/...' string) to its handler."""
    parts = text.strip().split(maxsplit=1)
    name = parts[0].lstrip("/").lower()
    arg = parts[1] if len(parts) > 1 else ""
    name = _ALIASES.get(name, name)

    entry = _REGISTRY.get(name)
    if entry is None:
        ctx.ui.warning(f"Unknown command: /{name}. Type /help for the list.")
        return CommandResult(handled=True)
    return entry[0](ctx, arg)


# Import handler modules for their registration side effects. Deferred to the
# bottom so ``command`` / ``_REGISTRY`` already exist when the handlers load.
from . import about, clear, help, history  # noqa: E402,F401

__all__ = [
    "CommandContext",
    "CommandResult",
    "command",
    "dispatch",
    "is_command",
    "_REGISTRY",
]
