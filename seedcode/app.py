"""Application controller: onboarding flow and the interactive REPL.

Loads config, runs first-run onboarding if no API key is present, then enters the
chat loop. The loop is defensive: unexpected errors become friendly messages
rather than tracebacks. :func:`run` is the single entry point the CLI calls.
"""

from __future__ import annotations

import sys

from prompt_toolkit import PromptSession

from .commands import CommandContext, dispatch, is_command
from .config import load_config, save_config
from .core.chat import ChatEngine, ChatError
from .core.client import validate_key
from .core.models import AppConfig
from .memory import HistoryStore
from .ui import UI
from .ui.prompts import PT_STYLE, prompt_label


def _onboarding(ui: UI, config: AppConfig) -> AppConfig:
    """First-run experience: collect and validate an OpenRouter API key."""
    ui.panel(
        "Enter your OpenRouter API key to get started.\n"
        "No key?  Get one at https://openrouter.ai/keys",
        title="OpenRouter Setup",
    )

    session: PromptSession = PromptSession()
    while True:
        try:
            key = session.prompt(
                prompt_label("API Key > "),
                is_password=True,
                style=PT_STYLE,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            ui.blank()
            ui.dim("Setup cancelled.")
            sys.exit(0)

        if not key:
            ui.warning("Please paste your key, or press Ctrl+C to cancel.")
            continue

        with ui.thinking("Validating key"):
            result = validate_key(key)

        if result.ok:
            config.api_key = key
            save_config(config)
            ui.success(result.message)
            ui.blank()
            return config

        ui.error(result.message)
        ui.dim("Try again, or press Ctrl+C to cancel.")


def _handle_chat(ui: UI, engine: ChatEngine, history: HistoryStore, text: str) -> None:
    """Send a user turn to the model and stream the reply to screen."""
    engine.add_user(text)
    try:
        chunks = engine.stream_reply()
        # Spinner until the first token, then hand off to the live renderer.
        first = ""
        with ui.thinking():
            for piece in chunks:
                first = piece
                break
        with ui.streaming() as renderer:
            if first:
                renderer.feed(first)
            for piece in chunks:
                renderer.feed(piece)
        reply = renderer.text
        if reply.strip():
            engine.add_assistant(reply)
            history.save(engine.transcript)
        else:
            ui.dim("(no response)")
    except ChatError as exc:
        ui.error(str(exc))


def _repl(ui: UI, config: AppConfig) -> None:
    """Main interactive loop."""
    engine = ChatEngine(config)
    history = HistoryStore()
    ctx = CommandContext(ui=ui, config=config, engine=engine)
    session: PromptSession = PromptSession()

    while True:
        try:
            text = session.prompt(
                prompt_label(f"{config.username} > "),
                style=PT_STYLE,
            ).strip()
        except KeyboardInterrupt:
            # Ctrl+C cancels the current line, does not quit.
            ui.dim("(use /exit to quit)")
            continue
        except EOFError:
            # Ctrl+D exits cleanly.
            ui.blank()
            ui.dim("Goodbye — plant ideas, grow code.")
            return

        if not text:
            continue

        if is_command(text):
            result = dispatch(ctx, text)
            if result.should_exit:
                return
            continue

        ui.blank()
        _handle_chat(ui, engine, history, text)


def run(ui: UI) -> None:
    """Load config, run onboarding if needed, and enter the REPL."""
    config = load_config()
    ui.banner(config)

    if not config.is_configured():
        config = _onboarding(ui, config)

    _repl(ui, config)
