"""Desktop-related commands: /desktop (legacy → Assist), /computer,
/screenshot, /windows.

The old Desktop Mode was merged into Assist Mode — /desktop now routes
there. /computer shows engine status; /screenshot and /windows work
immediately (no Assist turn needed) so the user can sanity-check the
engine by hand.
"""

from __future__ import annotations

from rich.table import Table

from ..computer import INSTALL_HINT, is_available, missing_packages
from . import CommandContext, CommandResult, command
from .assist import disable_assist, enable_assist


@command("desktop", "Legacy alias for Assist Mode. Usage: /desktop [on|off]")
def _desktop(ctx: CommandContext, arg: str) -> CommandResult:
    raw = arg.strip().lower()
    if raw in ("on", "off"):
        enable = raw == "on"
    elif not raw:
        enable = not ctx.config.agent_mode  # bare /desktop toggles Assist
    else:
        ctx.ui.warning("Usage: /desktop [on|off]")
        return CommandResult()

    # Desktop Mode was merged into Assist Mode — route there transparently.
    ctx.ui.dim("(/desktop is now Assist Mode)")
    if enable:
        enable_assist(ctx.ui, ctx.config)
    else:
        disable_assist(ctx.ui, ctx.config)
    return CommandResult()


@command("computer", "Show Computer Engine status and desktop permissions")
def _computer(ctx: CommandContext, arg: str) -> CommandResult:
    ok, reason = is_available()

    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.dim", justify="right", no_wrap=True)
    table.add_column(style="seed.text")
    table.add_row("Mode", "Assist" if ctx.config.agent_mode else "Chat  (/assist on)")
    table.add_row("Engine", reason if not ok else "Available")
    missing = missing_packages()
    if missing:
        table.add_row("Missing", f"{', '.join(missing)}  →  {INSTALL_HINT}")

    if ok:
        try:
            from ..tools.desktop import get_controller

            table.add_row("Screen", get_controller().screen_info().split("\n")[0])
        except Exception:
            pass
        from ..tools import TOOL_REGISTRY

        names = sorted(n for n, t in TOOL_REGISTRY.items() if t.group == "desktop")
        table.add_row("Tools", ", ".join(names))

    ctx.ui.panel(table, title="Computer Engine")
    return CommandResult()


@command("screenshot", "Capture a screenshot now. Usage: /screenshot [path]")
def _screenshot(ctx: CommandContext, arg: str) -> CommandResult:
    ok, reason = is_available()
    if not ok:
        ctx.ui.error(reason)
        return CommandResult()
    from pathlib import Path

    from ..tools.desktop import get_controller
    from ..computer.controller import ComputerError

    save_to = Path(arg.strip()).expanduser() if arg.strip() else None
    try:
        path = get_controller().screenshot(save_to=save_to)
    except ComputerError as exc:
        ctx.ui.error(str(exc))
        return CommandResult()
    ctx.ui.success(f"Screenshot saved: {path}")
    return CommandResult()


@command("windows", "List all open windows")
def _windows(ctx: CommandContext, arg: str) -> CommandResult:
    ok, reason = is_available()
    if not ok:
        ctx.ui.error(reason)
        return CommandResult()
    from ..tools.desktop import get_controller
    from ..computer.controller import ComputerError

    try:
        listing = get_controller().list_windows()
    except ComputerError as exc:
        ctx.ui.error(str(exc))
        return CommandResult()
    ctx.ui.panel(listing, title="Open Windows")
    return CommandResult()
