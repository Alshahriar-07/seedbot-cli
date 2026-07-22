"""/doctor — diagnose configuration, network, and provider health.

Every check is best-effort and individually guarded: the doctor itself can
never crash the app, and it never prints tracebacks — just a table of
pass/warn/fail rows with actionable hints.
"""

from __future__ import annotations

import json

from rich.table import Table

from ..core.providers import ProviderError, get_provider
from ..utils.helpers import app_dir, config_path, history_dir
from . import CommandContext, CommandResult, command

_OK = "ok"
_WARN = "warn"
_FAIL = "fail"

_STYLE = {_OK: "seed.success", _WARN: "seed.warning", _FAIL: "seed.error"}
_MARK = {_OK: "PASS", _WARN: "WARN", _FAIL: "FAIL"}


def _check_config_file() -> tuple[str, str]:
    path = config_path()
    if not path.exists():
        return _WARN, "no config file yet (first run) — it is created on save"
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return _OK, str(path)
    except (OSError, ValueError) as exc:
        return _FAIL, f"config.json unreadable ({exc}) — defaults are used"


def _check_storage() -> tuple[str, str]:
    probe = history_dir() / ".doctor-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return _OK, str(app_dir())
    except OSError as exc:
        return _FAIL, f"cannot write to {app_dir()} ({exc}) — history/config won't persist"


def _check_desktop(config) -> tuple[str, str]:
    """Computer Engine availability (only a WARN when desktop mode is off)."""
    from ..computer import is_available

    ok, reason = is_available()
    if ok:
        state = "enabled" if config.desktop_mode else "available (off — /desktop on)"
        return _OK, state
    return (_FAIL if config.desktop_mode else _WARN), reason


def _run_checks(config) -> list[tuple[str, str, str]]:
    """Return (status, check name, detail) rows."""
    rows: list[tuple[str, str, str]] = []

    status, detail = _check_config_file()
    rows.append((status, "Config file", detail))

    status, detail = _check_storage()
    rows.append((status, "Data directory", detail))

    status, detail = _check_desktop(config)
    rows.append((status, "Desktop control", detail))

    try:
        provider = get_provider(config.provider)
        rows.append((_OK, "Active provider", provider.label))
    except ProviderError as exc:
        rows.append((_FAIL, "Active provider", str(exc)))
        return rows  # nothing else is checkable without a provider

    provider.prepare(config)  # bind checks to the configured sub-backend
    if provider.requires_key:
        key = config.get_api_key(provider.id).strip()
        if not key:
            rows.append((_FAIL, "API key", "missing — run /apikey"))
        else:
            try:
                result = provider.validate_key(key)
                rows.append(
                    (_OK if result.ok else _FAIL, "API key", result.message)
                )
            except Exception:  # validation itself must never explode
                rows.append((_WARN, "API key", "could not be validated right now"))
    else:
        rows.append((_OK, "API key", "not required for this provider"))

    if config.model:
        rows.append((_OK, "Model", config.model))
    else:
        rows.append((_FAIL, "Model", "not selected — run /model"))

    # Live connectivity: fetching the model list exercises DNS, TLS, and the
    # provider endpoint in one real request.
    try:
        models = provider.list_models(config)
        rows.append((_OK, "Provider reachable", f"{len(models)} models available"))
    except ProviderError as exc:
        rows.append((_FAIL, "Provider reachable", str(exc)))
    except Exception as exc:
        rows.append((_FAIL, "Provider reachable", f"unexpected error: {exc}"))

    return rows


@command("doctor", "Diagnose configuration, network, and provider health")
def _doctor(ctx: CommandContext, arg: str) -> CommandResult:
    with ctx.ui.thinking("Running diagnostics"):
        rows = _run_checks(ctx.config)

    table = Table.grid(padding=(0, 2))
    table.add_column(justify="left", no_wrap=True)
    table.add_column(style="seed.text", no_wrap=True)
    table.add_column(style="seed.dim")
    for status, name, detail in rows:
        table.add_row(
            f"[{_STYLE[status]}]{_MARK[status]}[/{_STYLE[status]}]", name, detail
        )
    ctx.ui.panel(table, title="Doctor")

    if any(status == _FAIL for status, _, _ in rows):
        ctx.ui.dim("Fix the FAIL rows above; run /doctor again to re-check.")
    else:
        ctx.ui.success("Everything looks healthy.")
    return CommandResult()
