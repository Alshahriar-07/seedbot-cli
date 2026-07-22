"""Legacy commands: /agent and /permission.

The old Agent Mode was merged into Assist Mode — /agent now routes there.
/permission keeps its dedicated interactive picker; /index and /tools stay
as inspection commands.
"""

from __future__ import annotations

from ..config import save_config
from ..tools import TOOL_REGISTRY, PermissionManager, PermissionMode
from ..tools.filesystem import build_index
from ..ui.selector import Option, select
from . import CommandContext, CommandResult, command
from .assist import disable_assist, enable_assist


@command("agent", "Legacy alias for Assist Mode. Usage: /agent [on|off]")
def _agent(ctx: CommandContext, arg: str) -> CommandResult:
    raw = arg.strip().lower()
    if raw in ("on", "off"):
        enable = raw == "on"
    elif not raw:
        enable = not ctx.config.agent_mode  # bare /agent toggles
    else:
        ctx.ui.warning("Usage: /agent [on|off]")
        return CommandResult()

    # Agent Mode was merged into Assist Mode — route there transparently.
    ctx.ui.dim("(/agent is now Assist Mode)")
    if enable:
        enable_assist(ctx.ui, ctx.config)
    else:
        disable_assist(ctx.ui, ctx.config)
    return CommandResult()


@command("permission", "Show or set the Assist permission mode", aliases=("perm",))
def _permission(ctx: CommandContext, arg: str) -> CommandResult:
    raw = arg.strip()
    detail = {
        PermissionMode.READ_ONLY: "inspect only — no writes, no commands",
        PermissionMode.WORKSPACE: "edit and run inside this directory only",
        PermissionMode.DESKTOP: "control this computer (mouse, keyboard, apps)",
        PermissionMode.FULL_SYSTEM: "no path restriction + sensitive actions (use with care)",
    }
    if not raw:
        current = PermissionMode.parse(ctx.config.permission_mode)
        chosen = select(
            [
                Option(mode.label, mode.value_str, detail=detail[mode])
                for mode in PermissionMode
            ],
            title="Permission Level",
            initial=current.value_str,
            searchable=False,
            hint="↑↓ move   Enter select   Esc keep current",
        )
        if chosen is None:
            ctx.ui.dim(f"Permission unchanged ({current.label}).")
            return CommandResult()
        raw = str(chosen)

    try:
        mode = PermissionMode.parse(raw)
    except ValueError as exc:
        ctx.ui.warning(str(exc))
        return CommandResult()
    ctx.config.permission_mode = mode.value_str
    save_config(ctx.config)
    ctx.ui.success(f"Permission mode set to {mode.label}.")
    return CommandResult()


@command("index", "Show a compact tree of the current project")
def _index(ctx: CommandContext, arg: str) -> CommandResult:
    perm = PermissionManager(mode=PermissionMode.READ_ONLY)
    ctx.ui.panel(build_index(perm), title="Project Index")
    return CommandResult()


@command("tools", "List the tools available in Assist Mode")
def _tools(ctx: CommandContext, arg: str) -> CommandResult:
    from ..ui.layout import columns_grid

    rows = []
    for name in sorted(TOOL_REGISTRY):
        tool = TOOL_REGISTRY[name]
        kind = "changes files/system" if tool.mutates else "read-only"
        rows.append((name, f"{tool.description}  ({kind})"))
    ctx.ui.panel(
        columns_grid(rows, ("seed.primary", "seed.text")), title="Assist Tools"
    )
    return CommandResult()
