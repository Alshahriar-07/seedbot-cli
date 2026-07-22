"""Application controller: startup dashboard, chat REPL, and the main menu.

Startup renders the dashboard once and drops straight into the chat prompt;
/exit from chat reaches the interactive main menu (arrow keys + fuzzy
filter — no numbers anywhere). Chat can only begin once setup is complete —
otherwise the guided chain provider -> API key -> validate -> fetch models
-> select -> save runs first. All actions are guarded: no failure may crash
the application.

Global shortcuts at the chat prompt: Ctrl+K command palette, Ctrl+P project
file search, Ctrl+R history, Ctrl+/ shortcut reference, Ctrl+, settings,
Ctrl+L clear screen.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

from .commands import CommandContext, dispatch, is_command
from .commands.about import show_about
from .commands.help import show_shortcuts
from .commands.history import browse_history, settings_menu
from .commands.palette import open_file_search, open_palette
from .commands.provider import apikey_menu, select_model, select_provider
from .commands.theme import pick_theme
from .config import load_config
from .core.agent import AgentEngine, strip_tool_blocks
from .core.chat import ChatEngine, ChatError
from .core.models import AppConfig
from .core.providers import PROVIDERS, provider_label
from .core.providers.freemodel import AUTO_MODEL
from .memory import HistoryStore
from .tools import PermissionManager, PermissionMode
from .ui import UI
from .ui.badges import badge_for_status
from .ui.menu import MenuItem, run_menu
from .ui.textbox import prompt_label
from .ui.theme import pt_style, set_active_theme
from .utils.logger import get_logger

_log = get_logger("app")

# Sentinels returned by chat-prompt key bindings (never valid user text).
_KEY_ACTIONS = {
    "__palette__": "palette",
    "__files__": "files",
    "__history__": "history",
    "__shortcuts__": "shortcuts",
    "__settings__": "settings",
}


def _provider_status(config: AppConfig) -> str:
    """Menu status line: the active provider, or 'Not Configured'."""
    ready = config.provider == "ollama" or bool(config.get_api_key().strip())
    return provider_label(config.provider) if ready else "Not Configured"


def _model_status(config: AppConfig) -> str:
    """Menu status line: the selected model, or 'Not Selected'."""
    if not config.model:
        return "Not Selected"
    if config.model == AUTO_MODEL:
        return "Auto (best free model)"
    return config.model


def _key_status(config: AppConfig) -> str:
    """Menu status line: the active provider's masked key."""
    provider = PROVIDERS.get(config.provider)
    if provider is not None and not provider.requires_key:
        return "(not required)"
    return config.masked_key()


def _main_menu(config: AppConfig):
    """The interactive main menu; returns an action id or None (exit)."""
    provider = PROVIDERS.get(config.provider)
    badge = badge_for_status(provider.status if provider is not None else "")
    return run_menu(
        [
            MenuItem("Start Chat", "chat", status=_model_status(config), badge=badge),
            MenuItem("Provider", "provider", status=_provider_status(config)),
            MenuItem("API Key", "apikey", status=_key_status(config)),
            MenuItem("Model", "model", status=_model_status(config)),
            MenuItem("Settings", "settings"),
            MenuItem("Theme", "theme", status=config.theme),
            MenuItem("About", "about"),
            MenuItem("Exit", "exit"),
        ],
        title="Seed Code",
        hint="↑↓ move   type to filter   Enter select   Esc exit",
        initial="chat",
    )


def _guided_setup(ui: UI, config: AppConfig) -> bool:
    """Provider -> API key -> validate -> fetch models -> select -> save.

    Reuses the exact /provider and /model flows so setup and mid-session
    switching behave identically. Returns True once chat is possible.
    """
    ui.info("Setup: choose a provider to get started.")
    if not select_provider(ui, config):
        return False
    if not config.model:
        select_model(ui, config)
    return config.is_configured()


def _handle_chat(ui: UI, engine: ChatEngine, history: HistoryStore, text: str) -> None:
    """Send a user turn to the model and stream the reply to screen."""
    engine.add_user(text)
    renderer = None
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
    except ChatError as exc:
        # Drop the unanswered user turn so a retry doesn't send two
        # consecutive user messages (strict APIs reject that shape).
        engine.drop_last_user()
        ui.error(str(exc))
        return
    except KeyboardInterrupt:
        # Ctrl+C cancels this response only — the session keeps going.
        ui.blank()
        ui.dim("(response cancelled)")

    reply = renderer.text if renderer is not None else ""
    if reply.strip():
        engine.add_assistant(reply)
        history.save(engine.transcript)
    else:
        # No reply (empty response, or cancelled before the first token):
        # forget the user turn so the transcript stays alternating.
        engine.drop_last_user()
        if renderer is not None:
            ui.dim("(no response)")


def _handle_agent(ui: UI, agent: AgentEngine, history: HistoryStore, text: str) -> None:
    """Run one full Assist turn (tool loop) and render the final answer."""

    try:
        with ui.thinking("Working"):
            reply = agent.run_turn(text)
    except ChatError as exc:
        ui.error(str(exc))
        return
    except KeyboardInterrupt:
        # Ctrl+C aborts the remaining Assist steps; work already done stays.
        ui.blank()
        ui.dim("(assist turn cancelled — completed tool actions were kept)")
        return

    final = strip_tool_blocks(reply)
    if final.strip():
        with ui.streaming() as renderer:
            renderer.feed(final)
    else:
        ui.dim("(no response)")
    history.save(agent.transcript)


def _make_agent(ui: UI, config: AppConfig) -> AgentEngine:
    """Build an Assist engine bound to the CWD and the configured permissions."""
    # Lazy import (matching _make_desktop_session): the optional, platform-
    # specific computer package stays out of app.py's top-level import graph.
    from .computer import is_available

    permissions = PermissionManager(level=PermissionMode.parse(config.permission_mode))
    # Desktop capability is a property of the permission level now: attach the
    # Computer Engine gate whenever the level is Desktop or higher and the
    # engine is actually available on this machine.
    if permissions.level.allows_desktop and is_available()[0]:
        permissions.desktop = _make_desktop_session(ui)
    permissions.gate = _make_action_gate(ui)
    # Live terminal output: echo each line a running command prints.
    permissions.on_output = lambda line: ui.dim(f"  │ {line[:200]}")

    def narrate(kind: str, detail: str) -> None:
        if kind == "call":
            ui.dim(f"  ⚒ {detail}")
        elif kind == "error":
            ui.dim(f"  ✖ {detail.splitlines()[0][:120]}")
        elif kind == "limit":
            ui.warning(f"Assist stopped: {detail}")

    return AgentEngine(config, permissions, on_event=narrate)


def _make_action_gate(ui: UI):
    """Dangerous-action gate wired to the interactive permission dialog.

    Note: the Assist engine (and thus this gate) is rebuilt on permission-mode
    changes, so session "Always" grants reset then — conservative on purpose.
    """
    from .tools.permissions import ACTION_LABELS, ActionGate, ActionGrant

    def confirm(category: str, description: str) -> ActionGrant:
        label = ACTION_LABELS.get(category, category)
        answer = ui.confirm_tool_action(label, description)
        return {
            "y": ActionGrant.ONCE,
            "a": ActionGrant.ALWAYS,
        }.get(answer, ActionGrant.DENY)

    return ActionGate(confirm=confirm)


def _make_desktop_session(ui: UI):
    """Desktop Control gate wired to the interactive permission dialog."""
    from .computer import DesktopGrant, DesktopSession
    from .computer.permissions import CATEGORY_LABELS

    def confirm(category: str, description: str) -> DesktopGrant:
        label = CATEGORY_LABELS.get(category, category)
        answer = ui.confirm_desktop(label, description)
        return {
            "y": DesktopGrant.ONCE,
            "a": DesktopGrant.ALWAYS,
        }.get(answer, DesktopGrant.DENY)

    return DesktopSession(enabled=True, confirm=confirm)


def _run_key_action(ui: UI, ctx: CommandContext, config: AppConfig, action: str) -> None:
    """Dispatch one chat-prompt shortcut sentinel."""
    try:
        if action == "palette":
            open_palette(ctx)
        elif action == "files":
            open_file_search(ctx)
        elif action == "history":
            browse_history(ui, config)
        elif action == "shortcuts":
            show_shortcuts(ui)
        elif action == "settings":
            settings_menu(ui, config)
    except (KeyboardInterrupt, EOFError):
        ui.dim("Cancelled.")
    except Exception as exc:  # a broken picker must not kill the REPL
        _log.exception("shortcut action failed: %s", action)
        ui.error(f"Something went wrong: {exc}")


def _chat_loop(
    ui: UI,
    config: AppConfig,
    engine: ChatEngine,
    history: HistoryStore,
    session: PromptSession,
) -> None:
    """Interactive chat until /exit (returns to the main menu)."""
    ctx = CommandContext(ui=ui, config=config, engine=engine)
    ui.dim(
        "Type /help for commands, /exit for the menu — "
        "Ctrl+K palette, Ctrl+P files, Ctrl+/ shortcuts."
    )

    # The Assist engine is built lazily on the first assist-mode turn and
    # rebuilt when the permission or desktop mode changes (its system
    # prompt and permission gates reflect both).
    agent: AgentEngine | None = None
    agent_perm = config.permission_mode

    while True:
        try:
            raw = session.prompt(
                prompt_label(f"{config.username} > "),
                style=pt_style(),
            )
        except KeyboardInterrupt:
            # Ctrl+C cancels the current line, does not quit.
            ui.dim("(use /exit for the menu)")
            continue
        except EOFError:
            # Ctrl+D returns to the menu.
            ui.blank()
            return

        if raw in _KEY_ACTIONS:
            _run_key_action(ui, ctx, config, _KEY_ACTIONS[raw])
            continue

        text = raw.strip()
        if not text:
            continue

        if is_command(text):
            backend_before = config.provider
            try:
                result = dispatch(ctx, text)
            except (KeyboardInterrupt, EOFError):
                ui.dim("Cancelled.")
                continue
            except Exception as exc:  # a broken command must not kill the REPL
                _log.exception("command failed: %s", text.split()[0])
                ui.error(f"Command failed: {exc}")
                continue
            if result.should_exit:
                return
            if config.provider != backend_before:
                # Provider switched mid-chat: the whole backend state
                # (client, models, history) refreshes — start fresh.
                ui.dim("(provider changed — returning to the menu)")
                return
            continue

        ui.blank()
        if config.agent_mode:
            if agent is None or agent_perm != config.permission_mode:
                agent = _make_agent(ui, config)
                agent_perm = config.permission_mode
            _handle_agent(ui, agent, history, text)
        else:
            _handle_chat(ui, engine, history, text)


def _build_chat_session(ui: UI) -> PromptSession:
    """The chat PromptSession with the global shortcut bindings attached."""
    kb = KeyBindings()

    kb.add("c-k")(lambda e: e.app.exit(result="__palette__"))
    kb.add("c-p")(lambda e: e.app.exit(result="__files__"))
    kb.add("c-r")(lambda e: e.app.exit(result="__history__"))
    # Ctrl+/ reaches terminals as Ctrl+_; bind both spellings.
    kb.add("c-_")(lambda e: e.app.exit(result="__shortcuts__"))

    @kb.add("c-l")
    def _(event) -> None:
        ui.console.clear()
        event.app.renderer.clear()

    # Ctrl+, (settings) — where the terminal delivers it distinctly.
    try:
        kb.add("c-,")(lambda e: e.app.exit(result="__settings__"))
    except (ValueError, KeyError):
        pass  # terminals without a distinct Ctrl+, sequence

    return PromptSession(key_bindings=kb)


def run(ui: UI) -> None:
    """Show the startup dashboard, drop straight into chat, then the menu.

    The dashboard renders exactly once at launch; the chat prompt follows
    immediately (after guided setup when nothing is configured yet). The
    interactive menu remains available via /exit for provider/model/settings.
    """
    config = load_config()
    set_active_theme(config.theme)
    ui.apply_theme(config.theme)
    ui.banner(config)
    _log.info(
        "started: provider=%s model=%s configured=%s",
        config.provider,
        config.model or "(none)",
        config.is_configured(),
    )

    active_backend = config.provider
    engine = ChatEngine(config)
    history = HistoryStore(provider_id=active_backend)
    chat_session = _build_chat_session(ui)

    # Straight into chat after the dashboard — the menu is one /exit away.
    try:
        if config.is_configured() or _guided_setup(ui, config):
            if config.provider != active_backend:
                # Guided setup switched providers: rebuild the backend state.
                active_backend = config.provider
                engine = ChatEngine(config)
                history = HistoryStore(provider_id=active_backend)
            _chat_loop(ui, config, engine, history, chat_session)
        else:
            ui.dim("Setup incomplete — chat needs a provider and a model.")
    except (KeyboardInterrupt, EOFError):
        ui.dim("Cancelled.")
    except Exception as exc:  # startup chat must never crash the app
        _log.exception("startup chat failed")
        ui.error(f"Something went wrong: {exc}")

    while True:
        if config.provider != active_backend:
            # Provider switched: rebuild everything below it — fresh chat
            # backend/context and the new provider's own history store.
            _log.info("backend switched: %s -> %s", active_backend, config.provider)
            active_backend = config.provider
            engine = ChatEngine(config)
            history = HistoryStore(provider_id=active_backend)

        try:
            choice = _main_menu(config)
        except (KeyboardInterrupt, EOFError):
            ui.blank()
            ui.dim("Goodbye — plant ideas, grow code.")
            return

        try:
            if choice == "chat":
                if not config.is_configured() and not _guided_setup(ui, config):
                    ui.dim("Setup incomplete — chat needs a provider and a model.")
                    continue
                _chat_loop(ui, config, engine, history, chat_session)
            elif choice == "provider":
                select_provider(ui, config)
            elif choice == "apikey":
                apikey_menu(ui, config)
            elif choice == "model":
                select_model(ui, config)
            elif choice == "settings":
                settings_menu(ui, config)
            elif choice == "theme":
                pick_theme(ui, config)
            elif choice == "about":
                show_about(ui, config)
            elif choice in ("exit", None):
                ui.dim("Goodbye — plant ideas, grow code.")
                return
        except (KeyboardInterrupt, EOFError):
            ui.dim("Cancelled.")
        except Exception as exc:  # menu actions must never crash the app
            _log.exception("menu action failed: %s", choice)
            ui.error(f"Something went wrong: {exc}")
