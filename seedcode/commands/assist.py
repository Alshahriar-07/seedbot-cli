"""Assist Mode: unified AI + computer control.

/assist on  — enables the full capability set (AI, filesystem, terminal,
              git, browser, keyboard, mouse, windows, vision, OCR, desktop
              automation).
/assist off — back to plain chat.

Assist Mode is the ONLY automation mode Seed Code exposes. The old Agent
and Desktop modes were merged into it; their commands now route here.
"""

from __future__ import annotations

from rich.table import Table

from ..computer import is_available
from ..config import save_config
from ..tools import TOOL_REGISTRY, PermissionMode
from . import CommandContext, CommandResult, command

# The Assist capability set, in display order. Desktop-engine rows are
# marked so they can be dimmed when the Computer Engine is unavailable.
_CAPABILITIES: tuple[tuple[str, str, bool], ...] = (
    ("AI", "Chat, reasoning, and code generation", False),
    ("Filesystem", "Read, write, edit, search, and organise files", False),
    ("Terminal", "Run shell commands with live output", False),
    ("Git", "Status, diff, log, commit, push, pull", False),
    ("Browser", "Navigate, click, type, search", True),
    ("Keyboard", "Type, hotkeys, shortcuts", True),
    ("Mouse", "Move, click, drag, scroll", True),
    ("Windows", "List, focus, open, close", True),
    ("Vision", "See and understand the screen", True),
    ("OCR", "Read text from the screen", True),
    ("Desktop Automation", "Multi-step computer control", True),
)


@command("assist", "Enable/disable Assist Mode (unified AI + computer control)")
def _assist(ctx: CommandContext, arg: str) -> CommandResult:
    raw = arg.strip().lower()
    if raw in ("on", "off"):
        enable = raw == "on"
    elif not raw:
        # Bare /assist: show status
        _show_status(ctx)
        return CommandResult()
    else:
        ctx.ui.warning("Usage: /assist [on|off]")
        return CommandResult()

    if enable:
        enable_assist(ctx.ui, ctx.config)
    else:
        disable_assist(ctx.ui, ctx.config)
    return CommandResult()


def capability_table(desktop_ok: bool) -> Table:
    """The Assist capability list (✓ rows; desktop rows dim when missing)."""
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", no_wrap=True)
    table.add_column()
    for name, detail, needs_desktop in _CAPABILITIES:
        if needs_desktop and not desktop_ok:
            table.add_row(f"[seed.dim]○ {name}[/seed.dim]", f"[seed.dim]{detail}[/seed.dim]")
        else:
            table.add_row(f"[seed.success]✓ {name}[/seed.success]", f"[seed.text]{detail}[/seed.text]")
    return table


def enable_assist(ui, config) -> None:
    """Enable Assist Mode: the full capability set in one switch."""
    config.agent_mode = True

    # Desktop capabilities require the Computer Engine. When available, Assist
    # runs at the ``desktop`` level so the AI can drive the computer; otherwise
    # it stays at ``workspace`` (AI + filesystem + terminal + git still work).
    desktop_ok, desktop_reason = is_available()
    config.permission_mode = (
        PermissionMode.DESKTOP.value_str if desktop_ok
        else PermissionMode.WORKSPACE.value_str
    )
    save_config(config)

    ui.success("Assist Mode ON")
    ui.blank()
    ui.panel(capability_table(desktop_ok), title="Assist Mode")
    if not desktop_ok:
        ui.dim(f"Desktop capabilities unavailable: {desktop_reason}")
    ui.blank()

    level_label = "desktop" if desktop_ok else "workspace"
    ui.dim(f"Permission level: {level_label} — change in Settings › Advanced or /permission.")
    ui.dim("Dangerous actions ask first: Allow Once / Always Allow / Deny.")
    ui.dim("The AI picks the right tools for each task automatically.")


def disable_assist(ui, config) -> None:
    """Disable Assist Mode: back to plain chat."""
    config.agent_mode = False
    # Drop back to the safe editing level (removes desktop capability).
    config.permission_mode = PermissionMode.WORKSPACE.value_str
    save_config(config)
    ui.success("Assist Mode OFF — back to plain chat")


def _show_status(ctx: CommandContext) -> None:
    """Show current Assist Mode status."""
    on = ctx.config.agent_mode
    desktop_ok, desktop_reason = is_available()

    table = Table.grid(padding=(0, 3))
    table.add_column(style="seed.dim", justify="right", no_wrap=True)
    table.add_column()

    state = "[seed.accent]ON[/seed.accent]" if on else "[seed.dim]OFF[/seed.dim]"
    table.add_row("Assist Mode", state)
    table.add_row("Mode", "Assist" if on else "Chat")
    if not desktop_ok:
        table.add_row("Desktop", f"Unavailable: {desktop_reason}")
    table.add_row("Permission", ctx.config.permission_mode.replace("_", " ").title())

    core_tools = [n for n, t in TOOL_REGISTRY.items() if t.group == "core"]
    desktop_tools = [n for n, t in TOOL_REGISTRY.items() if t.group == "desktop"]
    table.add_row("Available tools", f"{len(core_tools)} core, {len(desktop_tools)} desktop")

    ctx.ui.panel(table, title="Assist Mode")
    ctx.ui.blank()
    ctx.ui.dim("Toggle with: /assist on | /assist off")
