"""Provider and model selection: /provider, /model.

Both commands are fully interactive: arrow keys move, typing fuzzy-filters
the live list, Enter confirms, Esc cancels. The provider selector shows
status badges, the backend, and each provider's current model; the model
selector groups the catalogue by family. The same flows are reused by
first-run onboarding (:mod:`seedcode.app`), so setup and mid-session
switching behave identically.
"""

from __future__ import annotations

from ..config import save_config
from ..core.providers import (
    PROVIDERS,
    ModelInfo,
    Provider,
    ProviderError,
    get_provider,
)
from ..core.providers.base import STATUS_CONNECTED, STATUS_OFFLINE
from ..core.providers.freemodel import AUTO_MODEL
from ..ui.badges import badge_for_status
from ..ui.menu import MenuItem, run_menu
from ..ui.selector import Option, select
from ..ui.textbox import read_text
from . import CommandContext, CommandResult, command


# --- provider selection ------------------------------------------------------


def _resolve_provider(text: str) -> Provider | None:
    """Match user input against provider ids and labels (prefix-tolerant)."""
    t = text.strip().lower()
    if not t:
        return None
    for p in PROVIDERS.values():
        if t in (p.id, p.label.lower()):
            return p
    matches = [
        p
        for p in PROVIDERS.values()
        if p.id.startswith(t) or p.label.lower().startswith(t)
    ]
    return matches[0] if len(matches) == 1 else None


def _provider_backend(provider: Provider, config) -> str:
    if provider.id == "ollama":
        return "Local"
    return provider.backend_label or f"{provider.label} API"


def _provider_menu(ui, config) -> Provider | None:
    """Interactive provider selector: badge, backend, and current model."""
    options = []
    for p in PROVIDERS.values():
        entry = config.providers.get(p.id)
        model = entry.model if entry and entry.model else "—"
        if model == AUTO_MODEL:
            model = "Auto"
        options.append(
            Option(
                p.label,
                value=p.id,
                badge=badge_for_status(p.status),
                columns=(_provider_backend(p, config), model),
            )
        )
    chosen = select(
        options,
        title="Provider",
        hint="↑↓ move   type to filter   Enter select   Esc cancel",
        initial=config.provider,
    )
    if chosen is None:
        ui.dim("Cancelled.")
        return None
    return PROVIDERS[str(chosen)]


def _collect_key(ui, config, provider: Provider, *, replacing: bool = False) -> bool:
    """Prompt for, validate, and save an API key for ``provider``.

    Returns False when the user cancels. Only this provider's entry is
    written — other providers' keys are never touched.
    """
    provider.prepare(config)  # bind validation to the configured sub-backend
    if replacing:
        ui.info(f"Enter a new API key for {provider.label}.")
        ui.dim(f"Current: {config.masked_key(provider.id)}")
    else:
        ui.info(f"{provider.label} needs an API key.")
    if provider.key_hint:
        ui.dim(f"Key: {provider.key_hint}")
    while True:
        key = read_text("API Key > ", password=True)
        if key is None or not key:
            ui.dim("Cancelled — no key saved.")
            return False
        with ui.thinking("Validating key"):
            result = provider.validate_key(key)
        if result.ok:
            # Only a key that passed real authentication is ever saved.
            config.set_api_key(provider.id, key)
            save_config(config)
            provider.status = STATUS_CONNECTED
            ui.success(result.message)
            return True
        ui.error(result.message)
        ui.dim("Try again, or press Esc to cancel.")


def _ensure_ready(ui, config, provider: Provider) -> bool:
    """Make ``provider`` usable: collect+validate a key, or detect Ollama.

    Returns False only when the user cancels key entry; a stopped Ollama
    server is reported but not fatal (the user may start it later).
    """
    if not provider.requires_key:
        with ui.thinking("Checking Ollama"):
            running = provider.detect(config)
        provider.status = STATUS_CONNECTED if running else STATUS_OFFLINE
        if running:
            ui.success("Ollama server detected.")
        else:
            ui.warning(
                f"Ollama is not reachable at {config.ollama_host}. "
                "Start it with 'ollama serve' — chatting will fail until it runs."
            )
        return True

    if config.get_api_key(provider.id).strip():
        # Existing key: refresh this provider's connection status with a
        # real request so the selector badge reflects reality immediately.
        with ui.thinking(f"Checking {provider.label}"):
            provider.refresh_status(config)
        return True
    return _collect_key(ui, config, provider)


def select_provider(ui, config, target: str = "") -> bool:
    """Switch the active provider; returns True when the switch completed.

    Only ``active_provider`` changes — every provider keeps its own saved
    API key and model, so switching back restores them untouched.
    """
    chosen: Provider | None = None
    if target:
        chosen = _resolve_provider(target)
        if chosen is None:
            ui.warning(f"Unknown provider '{target}'.")
    if chosen is None:
        chosen = _provider_menu(ui, config)
    if chosen is None:
        return False

    previous = config.provider
    config.provider = chosen.id
    if not _ensure_ready(ui, config, chosen):
        config.provider = previous  # cancelled key entry: keep the old backend
        return False

    save_config(config)
    ui.success(f"Provider set to {chosen.label}.")
    # The provider's own saved model is active again automatically.
    if config.model:
        ui.dim(f"Model: {config.model}")
    else:
        ui.warning(f"No model selected for {chosen.label} yet — run /model.")
    return True


# --- model selection ---------------------------------------------------------


def _set_model(ui, config, model_id: str) -> None:
    # Written into the ACTIVE provider's own slot — other providers keep theirs.
    config.model = model_id
    save_config(config)
    ui.success(f"Model set to {model_id}")


def _match_model(models: list[ModelInfo], text: str) -> ModelInfo | None:
    """Exact id match first, then a unique case-insensitive substring."""
    t = text.strip().lower()
    for m in models:
        if m.id.lower() == t:
            return m
    partial = [m for m in models if t in m.id.lower() or t in m.label.lower()]
    return partial[0] if len(partial) == 1 else None


# Family keywords for grouping the model selector (checked in order).
_FAMILIES: tuple[tuple[str, str], ...] = (
    ("codex", "Codex"),
    ("claude", "Claude"),
    ("gpt", "GPT"),
    ("o1", "GPT"),
    ("o3", "GPT"),
    ("qwen", "Qwen"),
    ("deepseek", "DeepSeek"),
    ("gemini", "Gemini"),
    ("gemma", "Gemini"),
    ("llama", "Llama"),
    ("mistral", "Mistral"),
    ("mixtral", "Mistral"),
)


def _model_group(model: ModelInfo) -> str:
    """Family header for the grouped model selector."""
    hay = f"{model.id} {model.label}".lower()
    for needle, family in _FAMILIES:
        if needle in hay:
            return family
    if "/" in model.id:
        vendor = model.id.split("/", 1)[0]
        return vendor.replace("-", " ").title()
    return "Other"


def _model_options(models: list[ModelInfo], current: str) -> list[Option]:
    """Grouped, badge-carrying options for the model selector."""
    grouped: dict[str, list[ModelInfo]] = {}
    for m in models:
        grouped.setdefault(_model_group(m), []).append(m)
    options: list[Option] = []
    for family in sorted(grouped, key=lambda g: (g == "Other", g.lower())):
        for m in grouped[family]:
            detail = m.detail
            if m.label and m.label != m.id:
                detail = f"{m.label}   {m.detail}".strip()
            options.append(
                Option(
                    m.id,
                    value=m.id,
                    detail=detail,
                    group=family,
                    badge="ready" if m.id == current else "",
                )
            )
    return options


def _pick_model_interactive(ui, config, provider: Provider, models: list[ModelInfo]) -> None:
    """The interactive grouped model selector (plus Auto and OpenRouter modes)."""
    options: list[Option] = []
    if provider.supports_auto:
        options.append(
            Option(
                "Auto",
                value=AUTO_MODEL,
                detail="best free model picked per request",
                group="Modes",
                badge="ready" if config.model == AUTO_MODEL else "",
            )
        )
    if provider.id == "openrouter":
        mode = provider.extra_settings(config).get("mode", "free")
        other = "pro" if mode == "free" else "free"
        options.append(
            Option(
                f"Switch to {other.title()} models",
                value=f"__mode__{other}",
                detail=f"currently showing {mode} models",
                group="Modes",
            )
        )
    options.extend(_model_options(models, config.model))

    chosen = select(
        options,
        title=f"Model — {provider.label} ({len(models)} available)",
        hint="type to filter (fuzzy)   ↑↓ move   Enter select   Esc cancel",
        initial=config.model or None,
        max_rows=14,
    )
    if chosen is None:
        ui.dim("Cancelled.")
        return
    choice = str(chosen)
    if choice.startswith("__mode__"):
        ok, message = provider.set_extra_setting(config, "mode", choice[len("__mode__"):])
        if not ok:
            ui.warning(message)
            return
        save_config(config)
        ui.success(message)
        try:
            with ui.thinking("Fetching models"):
                refreshed = provider.list_models(config)
        except ProviderError as exc:
            ui.error(str(exc))
            return
        _pick_model_interactive(ui, config, provider, refreshed)
        return
    if choice == AUTO_MODEL:
        _set_model(ui, config, AUTO_MODEL)
        ui.dim("(Auto mode: the best free model is picked per request)")
        return
    _set_model(ui, config, choice)


def select_model(ui, config, target: str = "") -> None:
    """Browse the live model catalogue of the active provider and pick one.

    Providers with ``supports_auto`` additionally offer Auto mode: the best
    model is resolved from the live catalogue on every request.
    """
    try:
        provider = get_provider(config.provider)
    except ProviderError as exc:
        ui.error(str(exc))
        return
    if provider.requires_key and not config.get_api_key(provider.id).strip():
        ui.warning(f"{provider.label} has no API key yet — run /provider first.")
        return

    if target and provider.supports_auto and target.lower() in ("auto", "a"):
        _set_model(ui, config, AUTO_MODEL)
        ui.dim("(Auto mode: the best free model is picked per request)")
        return

    try:
        with ui.thinking("Fetching models"):
            models = provider.list_models(config)
    except ProviderError as exc:
        if target and provider.id == "aerolink":
            # AeroLink may not expose /v1/models; accept the typed id as-is.
            _set_model(ui, config, target)
            ui.dim("(model list unavailable — id saved without verification)")
        else:
            ui.error(str(exc))
        return

    if target:
        m = _match_model(models, target)
        if m is not None:
            _set_model(ui, config, m.id)
        else:
            ui.warning(f"No model matching '{target}'. Run /model to browse.")
        return

    _pick_model_interactive(ui, config, provider, models)


# --- command handlers --------------------------------------------------------


@command(
    "provider",
    "Select the active provider "
    "(OpenRouter, FreeModel Claude, FreeModel Codex, AeroLink, Ollama)",
)
def _provider_cmd(ctx: CommandContext, arg: str) -> CommandResult:
    select_provider(ctx.ui, ctx.config, arg.strip())
    return CommandResult()


@command("model", "Browse and select a model for the active provider", aliases=("show",))
def _model_cmd(ctx: CommandContext, arg: str) -> CommandResult:
    target = arg.strip()
    # Support the documented "/show model" phrasing.
    if target.lower().startswith("model"):
        target = target[len("model"):].strip()
    select_model(ctx.ui, ctx.config, target)
    return CommandResult()


def apikey_menu(ui, config) -> None:
    """Manage the ACTIVE provider's API key: view, replace, remove, validate."""
    try:
        provider = get_provider(config.provider)
    except ProviderError as exc:
        ui.error(str(exc))
        return
    if not provider.requires_key:
        ui.info(f"{provider.label} does not use an API key.")
        return

    while True:
        has_key = bool(config.get_api_key(provider.id).strip())
        choice = run_menu(
            [
                MenuItem("View", "view", status=config.masked_key(provider.id)),
                MenuItem("Replace", "replace"),
                MenuItem("Remove", "remove", disabled=not has_key),
                MenuItem("Validate", "validate", disabled=not has_key),
            ],
            title=f"API Key — {provider.label}",
            hint="↑↓ move   Enter select   Esc back",
        )
        if choice is None:
            return
        if choice == "view":
            if has_key:
                ui.info(f"{provider.label} key: {config.masked_key(provider.id)}")
            else:
                ui.dim("No key saved yet.")
        elif choice == "replace":
            _collect_key(ui, config, provider, replacing=has_key)
        elif choice == "remove":
            from ..ui.dialog import confirm_dialog

            if confirm_dialog(
                "Remove the saved key?", yes_label="Remove", no_label="Keep", danger=True
            ):
                config.set_api_key(provider.id, "")
                save_config(config)
                ui.success(f"{provider.label} key removed.")
            else:
                ui.dim("Key kept.")
        elif choice == "validate":
            provider.prepare(config)
            with ui.thinking("Validating key"):
                result = provider.validate_key(config.get_api_key(provider.id))
            if result.ok:
                ui.success(result.message)
            else:
                ui.error(result.message)


@command("apikey", "View, replace, remove, or validate the active provider's key",
         aliases=("key",))
def _apikey_cmd(ctx: CommandContext, arg: str) -> CommandResult:
    key = arg.strip()
    if key:
        # Key given inline: validate and save it directly.
        try:
            provider = get_provider(ctx.config.provider)
        except ProviderError as exc:
            ctx.ui.error(str(exc))
            return CommandResult()
        if not provider.requires_key:
            ctx.ui.info(f"{provider.label} does not use an API key.")
            return CommandResult()
        provider.prepare(ctx.config)
        with ctx.ui.thinking("Validating key"):
            result = provider.validate_key(key)
        if result.ok:
            ctx.config.set_api_key(provider.id, key)
            save_config(ctx.config)
            ctx.ui.success(result.message)
        else:
            ctx.ui.error(result.message)
        return CommandResult()

    apikey_menu(ctx.ui, ctx.config)
    return CommandResult()
