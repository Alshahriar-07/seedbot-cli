"""The Seed Code startup dashboard.

A single branded panel shown exactly once at application startup: the ASCII
logo, tagline and credits on the left, and a live "Current Session" summary
(provider, backend, model, status, context, history) on the right. Wide
terminals get the two-column layout with a vertical divider; narrow terminals
stack the session block below the logo. Every width decision is derived from
the live console size and measured content — nothing is padded by hand.

Rendering uses plain Rich primitives (Panel, Columns, Table.grid, Rule) so the
dashboard displays identically in Windows Terminal, PowerShell, CMD, Linux and
macOS terminals; legacy Windows consoles get pure-ASCII fallbacks.
"""

from __future__ import annotations

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .. import APP_NAME, TAGLINE, __version__
from ..core.models import AppConfig
from ..core.providers import PROVIDERS, provider_label
from ..core.providers.base import STATUS_CONNECTED, STATUS_UNKNOWN

_LOGO_LINES = [
    r"███████╗███████╗███████╗██████╗      ██████╗ ██████╗ ██████╗ ███████╗",
    r"██╔════╝██╔════╝██╔════╝██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    r"███████╗█████╗  █████╗  ██║  ██║    ██║     ██║   ██║██║  ██║█████╗ ",
    r"╚════██║██╔══╝  ██╔══╝  ██║  ██║    ██║     ██║   ██║██║  ██║██╔══╝ ",
    r"███████║███████╗███████╗██████╔╝    ╚██████╗╚██████╔╝██████╔╝███████╗",
    r"╚══════╝╚══════╝╚══════╝╚═════╝      ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

# Pure-ASCII fallback for legacy Windows consoles (raster-font cmd.exe)
# where the block/box-drawing glyphs above render as garbage.
_LOGO_LINES_ASCII = [
    r" ____  _____ _____ ____     ____ ___  ____  _____ ",
    r"/ ___|| ____| ____|  _ \   / ___/ _ \|  _ \| ____|",
    r"\___ \|  _| |  _| | | | | | |  | | | | | | |  _|  ",
    r" ___) | |___| |___| |_| | | |__| |_| | |_| | |___ ",
    r"|____/|_____|_____|____/   \____\___/|____/|_____|",
]

_CREDIT = "Created by Al Shahriar Sowan"


# --- session state ----------------------------------------------------------
def _provider_ready(config: AppConfig) -> bool:
    """True when the active provider is selected and has what it needs."""
    provider = PROVIDERS.get(config.provider)
    if provider is None:
        return False
    return not provider.requires_key or bool(config.get_api_key().strip())


def _provider_value(config: AppConfig) -> str:
    """Provider display label."""
    if not _provider_ready(config):
        return "Not selected"
    return provider_label(config.provider)


def _backend_value(config: AppConfig) -> str:
    """The API family the active provider talks to (its own backend_label)."""
    if not _provider_ready(config):
        return "--"
    if config.provider == "ollama":
        return config.ollama_host
    provider = PROVIDERS.get(config.provider)
    if provider is not None and provider.backend_label:
        return provider.backend_label
    return f"{provider_label(config.provider)} API"


def _model_value(config: AppConfig) -> str:
    if not config.model:
        return "Not selected"
    if config.model == "auto":
        return "Auto (best free model)"
    return config.model


def _status_value(config: AppConfig, marker: str) -> Text:
    """Connection status from the provider's session cache (no network I/O)."""
    if not config.is_configured():
        return Text("Not configured", style="seed.dim")
    provider = PROVIDERS.get(config.provider)
    status = provider.status if provider is not None else STATUS_UNKNOWN
    if status == STATUS_CONNECTED:
        return Text(f"{marker} Connected", style="seed.success")
    if status == STATUS_UNKNOWN:
        # Configured but not probed yet — ready to chat, not yet verified.
        return Text(f"{marker} Ready", style="seed.success")
    return Text(f"{marker} {status}", style="seed.dim")


def _context_value(config: AppConfig) -> str:
    """Model context window — the live catalogue is not cached at startup."""
    return "--"


def _mode_value(config: AppConfig) -> str:
    """The user-facing mode: Chat or Assist (never Agent/Desktop)."""
    return "Assist" if config.agent_mode else "Chat"


# --- blocks -----------------------------------------------------------------
def _brand_block(legacy: bool) -> RenderableType:
    """Left side: the exact ASCII logo with tagline and author centered under it."""
    lines = _LOGO_LINES_ASCII if legacy else _LOGO_LINES
    logo = Text("\n".join(lines), style="seed.primary", no_wrap=True, overflow="crop")
    tagline = Text(TAGLINE, style="seed.accent")
    credit = Text(_CREDIT, style="seed.dim")
    return Group(
        Align.center(logo),
        Text(),
        Align.center(tagline),
        Text(),
        Align.center(credit),
    )


def _session_block(config: AppConfig, legacy: bool) -> RenderableType:
    """Right side: the dynamic Current Session summary."""
    marker = "*" if legacy else "●"
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="seed.accent", no_wrap=True)
    grid.add_column(style="seed.dim", no_wrap=True)
    grid.add_column(style="seed.text", overflow="fold")
    rows: list[tuple[str, RenderableType]] = [
        ("Provider", Text(_provider_value(config))),
        ("Backend", Text(_backend_value(config))),
        ("Model", Text(_model_value(config))),
        ("Mode", Text(_mode_value(config), style="seed.accent")),
        ("Status", _status_value(config, marker)),
        ("Context", Text(_context_value(config))),
        ("History", Text("Enabled")),
    ]
    for label, value in rows:
        grid.add_row(label, ":", value)
    return Group(
        Text("Current Session", style="seed.primary"),
        Rule(style="seed.dim", characters="-" if legacy else "─"),
        Text(),
        grid,
    )


def _logo_width(legacy: bool) -> int:
    lines = _LOGO_LINES_ASCII if legacy else _LOGO_LINES
    return max(len(line) for line in lines)


# --- dashboard --------------------------------------------------------------
def render_dashboard(console: Console, config: AppConfig) -> None:
    """Render the startup dashboard panel, adapting to the terminal width."""
    legacy = console.legacy_windows
    brand = _brand_block(legacy)
    session = _session_block(config, legacy)

    session_width = console.measure(session).maximum
    # Panel borders/padding (6) + column gutters and divider (5), all fixed
    # rendering overhead — the terminal width itself is never assumed.
    needed = _logo_width(legacy) + session_width + 11

    if console.size.width >= needed:
        # Two columns with a single vertical divider between them: a Table
        # whose outer edge is hidden renders only the column separator.
        body: RenderableType = Table(
            box=box.SQUARE,
            show_header=False,
            show_edge=False,
            border_style="seed.dim",
            padding=(0, 2),
            pad_edge=False,
        )
        body.add_column()
        body.add_column()
        body.add_row(brand, session)
    else:
        # Narrow terminals: stack the session block below the logo.
        body = Group(brand, Text(), Align.center(session))

    console.print(
        Panel(
            body,
            title=f"{APP_NAME} v{__version__}",
            title_align="left",
            border_style="seed.primary",
            padding=(1, 2),
        )
    )
