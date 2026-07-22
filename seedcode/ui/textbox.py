"""Styled text input: the one line-input component.

Wraps prompt_toolkit's PromptSession with the active theme, Esc-to-cancel,
and password masking. Everything that needs typed input (API keys, setting
values, chat itself is separate) goes through here so behaviour stays
identical everywhere: Enter submits, Esc/Ctrl+C/Ctrl+D cancel (None).
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings

from .theme import pt_style


def prompt_label(text: str) -> FormattedText:
    """Build a themed prompt label for prompt_toolkit."""
    return FormattedText([("class:prompt", text)])


def _escape_bindings() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def _(event) -> None:
        event.app.exit(exception=EOFError)

    return kb


def read_text(
    label: str,
    *,
    password: bool = False,
    default: str = "",
    placeholder: str = "",
) -> str | None:
    """Read one line of themed input; ``None`` means cancelled.

    Esc, Ctrl+C and Ctrl+D all cancel — the user is never trapped.
    """
    session: PromptSession = PromptSession(key_bindings=_escape_bindings())
    kwargs: dict = {}
    if placeholder:
        kwargs["placeholder"] = FormattedText([("class:sel.placeholder", placeholder)])
    try:
        return session.prompt(
            prompt_label(label),
            is_password=password,
            style=pt_style(),
            default=default,
            **kwargs,
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None


# Backwards-compatible alias (old prompts.read_line callers).
read_line = read_text
