"""Status bar and layout helpers.

:func:`session_statusbar` renders the one-line session summary (provider,
model, mode, connection badge) shown under interactive screens and after
mode switches. :mod:`layout` keeps the shared panel/column conventions in
one place so every screen composes the same way.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from ..core.models import AppConfig
from ..core.providers import PROVIDERS, provider_label
from .badges import badge_for_status, badge_text


def mode_label(config: AppConfig) -> str:
    """The user-facing mode: Chat or Assist (never Agent/Desktop)."""
    return "Assist" if config.agent_mode else "Chat"


def session_statusbar(console: Console, config: AppConfig) -> None:
    """Print the one-line session status: provider · model · mode · badge."""
    provider = PROVIDERS.get(config.provider)
    status = provider.status if provider is not None else ""
    badge = badge_text(badge_for_status(status))

    bar = Text()
    bar.append(" " + provider_label(config.provider), style="seed.primary")
    bar.append("  ·  ", style="seed.dim")
    bar.append(config.model or "no model", style="seed.text")
    bar.append("  ·  ", style="seed.dim")
    bar.append(f"Mode: {mode_label(config)}", style="seed.accent")
    bar.append("  ·  ", style="seed.dim")
    bar.append(badge, style="seed.dim")
    console.print(bar)
