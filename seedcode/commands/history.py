"""Data-inspection and settings commands: /history, /config, /settings.

The settings screen is a nested interactive tree with breadcrumbs
(Settings › Providers › FreeModel Claude); the history browser is a
searchable selector where Enter opens a transcript and Delete removes it.
"""

from __future__ import annotations

from pydantic import ValidationError
from rich.table import Table
from rich.text import Text

from ..config import save_config
from ..core.providers import PROVIDERS, ProviderError, get_provider, provider_label
from ..memory import delete_session, list_sessions, load_session
from ..tools import PermissionMode
from ..ui.selector import Option, select
from ..ui.textbox import read_text
from ..ui.tree import TreeNode, navigate
from . import CommandContext, CommandResult, command

# Settings editable via /settings, with a tiny parser per value type.
# (provider/model have their own dedicated commands with live validation.)
_SETTINGS = {
    "username": str,
    "stream": bool,
    "ollama_host": str,
    "max_tokens": int,
}


# --- history browser ---------------------------------------------------------


def _show_transcript(ui, provider_id: str, sid: str) -> None:
    """Render one saved session's messages."""
    messages = load_session(provider_id, sid)
    if not messages:
        ui.dim("This session is empty or could not be read.")
        return
    body = Text()
    for msg in messages[:60]:
        role = str(msg.get("role", "?"))
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        style = "seed.primary" if role == "user" else "seed.accent"
        body.append(f"{role}: ", style=style)
        snippet = content if len(content) <= 500 else content[:500] + " …"
        body.append(snippet + "\n\n", style="seed.text")
    if len(messages) > 60:
        body.append(f"({len(messages) - 60} more messages)", style="seed.dim")
    ui.panel(body, title=f"Session {sid}")


def browse_history(ui, config) -> None:
    """Interactive history: search, Enter opens, Delete removes."""
    provider_id = config.provider
    while True:
        sessions = list_sessions(provider_id)
        if not sessions:
            ui.dim(f"No saved sessions for {provider_label(provider_id)} yet.")
            return

        def remove(option: Option) -> bool:
            return delete_session(provider_id, str(option.value))

        chosen = select(
            [
                Option(sid, value=sid, detail=f"{count} messages")
                for sid, count in sessions
            ],
            title=f"History — {provider_label(provider_id)}",
            hint="↑↓ move   Enter open   Delete remove   Esc back",
            on_delete=remove,
            max_rows=14,
        )
        if chosen is None:
            return
        _show_transcript(ui, provider_id, str(chosen))


@command("history", "Browse the active provider's saved sessions")
def _history(ctx: CommandContext, arg: str) -> CommandResult:
    # History is per provider: only the active backend's sessions are shown.
    browse_history(ctx.ui, ctx.config)
    return CommandResult()


# --- configuration display ---------------------------------------------------


@command("config", "Show current configuration")
def _config(ctx: CommandContext, arg: str) -> CommandResult:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.dim", justify="right")
    table.add_column(style="seed.text")
    table.add_row("Active provider", provider_label(ctx.config.provider))
    table.add_row("Model", ctx.config.model or "(none — run /model)")
    table.add_row("", "")
    # Every provider keeps its own key + model; switching never loses them.
    for provider in PROVIDERS.values():
        entry = ctx.config.providers.get(provider.id)
        saved_model = entry.model if entry else ""
        if provider.requires_key:
            table.add_row(f"{provider.label} key", ctx.config.masked_key(provider.id))
        table.add_row(f"{provider.label} model", saved_model or "(none)")
    table.add_row("", "")
    table.add_row("Ollama host", ctx.config.ollama_host)
    table.add_row("Theme", ctx.config.theme)
    table.add_row("Username", ctx.config.username)
    table.add_row("Streaming", "on" if ctx.config.stream else "off")
    table.add_row("Max tokens", str(ctx.config.max_tokens))
    ctx.ui.panel(table, title="Configuration")
    return CommandResult()


# --- setting application -----------------------------------------------------


def apply_setting(ui, config, name: str, raw: str) -> None:
    """Parse, validate, apply, and persist one setting change.

    Global settings first; anything else routes to the ACTIVE provider's own
    settings (e.g. OpenRouter 'mode', Ollama 'host').
    """
    kind = _SETTINGS.get(name)
    if kind is None:
        try:
            provider = get_provider(config.provider)
        except ProviderError:
            provider = None
        if provider is not None and name in provider.extra_settings(config):
            ok, message = provider.set_extra_setting(config, name, raw)
            if ok:
                save_config(config)
                ui.success(message)
            else:
                ui.warning(message)
            return
        known = sorted(_SETTINGS)
        if provider is not None:
            known += sorted(provider.extra_settings(config))
        ui.warning(f"Unknown setting: {name}. Available: {', '.join(known)}")
        return

    value: object = raw
    if kind is bool:
        lowered = raw.lower()
        if lowered not in ("on", "off", "true", "false"):
            ui.warning(f"'{name}' expects on/off.")
            return
        value = lowered in ("on", "true")
    elif kind is int:
        try:
            value = int(raw)
        except ValueError:
            ui.warning(f"'{name}' expects a number.")
            return
        if value < 1:
            ui.warning(f"'{name}' must be at least 1.")
            return

    try:
        setattr(config, name, value)
    except ValidationError:
        ui.warning(f"Invalid value for '{name}': {raw}")
        return
    save_config(config)
    ui.success(f"{name} set to {value}")


# --- interactive settings tree ----------------------------------------------


def _edit_text_setting(ui, config, name: str, current: str) -> bool:
    value = read_text(f"{name} > ", default=current)
    if value is None or value == current:
        return True
    apply_setting(ui, config, name, value)
    return True


def _toggle_setting(ui, config, name: str, current: bool) -> bool:
    apply_setting(ui, config, name, "off" if current else "on")
    return True


def _choose_permission(ui, config) -> bool:
    detail = {
        PermissionMode.READ_ONLY: "inspect only — no writes, no commands",
        PermissionMode.WORKSPACE: "edit and run inside this directory only",
        PermissionMode.DESKTOP: "control this computer (mouse, keyboard, apps)",
        PermissionMode.FULL_SYSTEM: "no path restriction + sensitive actions (use with care)",
    }
    chosen = select(
        [Option(mode.label, mode.value_str, detail=detail[mode]) for mode in PermissionMode],
        title="Permission Level",
        initial=config.permission_mode,
        searchable=False,
        hint="↑↓ move   Enter select   Esc back",
    )
    if chosen is not None:
        config.permission_mode = str(chosen)
        save_config(config)
        ui.success(f"Permission mode set to {PermissionMode.parse(str(chosen)).label}.")
    return True


def _provider_settings_nodes(ui, config, provider) -> list[TreeNode]:
    """One editable node per provider-specific extra setting."""
    nodes: list[TreeNode] = []
    for name in provider.extra_settings(config):
        def edit(n=name, p=provider) -> bool:
            current = p.extra_settings(config).get(n, "")
            value = read_text(f"{n} > ", default=current)
            if value is None or value == current:
                return True
            ok, message = p.set_extra_setting(config, n, value)
            if ok:
                save_config(config)
                ui.success(message)
            else:
                ui.warning(message)
            return True

        nodes.append(
            TreeNode(
                name,
                action=edit,
                status_fn=lambda n=name, p=provider: p.extra_settings(config).get(n, ""),
            )
        )
    if not nodes:
        nodes.append(TreeNode(f"{provider.label} has no extra settings", action=lambda: True))
    return nodes


def settings_menu(ui, config) -> None:
    """Interactive nested settings with breadcrumbs.

    Settings › Providers › <provider> reaches each backend's own options;
    Appearance holds the theme picker; History, Models, Keyboard and
    Advanced hold the rest.
    """
    from .theme import pick_theme

    def providers_nodes() -> list[TreeNode]:
        nodes = []
        for provider in PROVIDERS.values():
            entry = config.providers.get(provider.id)
            model = entry.model if entry and entry.model else "no model"
            nodes.append(
                TreeNode(
                    provider.label,
                    build=lambda p=provider: _provider_settings_nodes(ui, config, p),
                    status=model,
                )
            )
        return nodes

    def clear_history() -> bool:
        from ..ui.dialog import confirm_dialog

        sessions = list_sessions(config.provider)
        if not sessions:
            ui.dim("No saved sessions to clear.")
            return True
        if confirm_dialog(
            f"Delete all {len(sessions)} saved sessions for "
            f"{provider_label(config.provider)}?",
            yes_label="Delete All",
            no_label="Keep",
            danger=True,
        ):
            removed = sum(
                1 for sid, _ in sessions if delete_session(config.provider, sid)
            )
            ui.success(f"Removed {removed} sessions.")
        else:
            ui.dim("History kept.")
        return True

    def show_shortcuts() -> bool:
        from .help import show_shortcuts as render

        render(ui)
        return True

    root = TreeNode(
        "Settings",
        build=lambda: [
            TreeNode("Providers", build=providers_nodes,
                     status_fn=lambda: provider_label(config.provider)),
            TreeNode(
                "Appearance",
                build=lambda: [
                    TreeNode("Theme", action=lambda: (pick_theme(ui, config), True)[1],
                             status_fn=lambda: config.theme),
                    TreeNode(
                        "Streaming",
                        action=lambda: _toggle_setting(ui, config, "stream", config.stream),
                        status_fn=lambda: "on" if config.stream else "off",
                    ),
                ],
            ),
            TreeNode(
                "History",
                build=lambda: [
                    TreeNode("Browse Sessions",
                             action=lambda: (browse_history(ui, config), True)[1]),
                    TreeNode("Clear History", action=clear_history),
                ],
            ),
            TreeNode(
                "Models",
                build=lambda: [
                    TreeNode(
                        "Max Tokens",
                        action=lambda: _edit_text_setting(
                            ui, config, "max_tokens", str(config.max_tokens)
                        ),
                        status_fn=lambda: str(config.max_tokens),
                    ),
                ],
            ),
            TreeNode("Keyboard", build=lambda: [
                TreeNode("Show Shortcuts", action=show_shortcuts),
            ]),
            TreeNode(
                "Advanced",
                build=lambda: [
                    TreeNode(
                        "Username",
                        action=lambda: _edit_text_setting(
                            ui, config, "username", config.username
                        ),
                        status_fn=lambda: config.username,
                    ),
                    TreeNode(
                        "Ollama Host",
                        action=lambda: _edit_text_setting(
                            ui, config, "ollama_host", config.ollama_host
                        ),
                        status_fn=lambda: config.ollama_host,
                    ),
                    TreeNode("Permission Mode",
                             action=lambda: _choose_permission(ui, config),
                             status_fn=lambda: config.permission_mode),
                ],
            ),
        ],
    )
    navigate(root)


@command("settings", "Open interactive settings (or /settings <name> <value>)")
def _settings(ctx: CommandContext, arg: str) -> CommandResult:
    parts = arg.split(maxsplit=1)
    if len(parts) >= 2:
        apply_setting(ctx.ui, ctx.config, parts[0].lower(), parts[1].strip())
        return CommandResult()
    settings_menu(ctx.ui, ctx.config)
    return CommandResult()
