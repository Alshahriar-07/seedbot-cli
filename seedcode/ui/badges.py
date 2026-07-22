"""Status badges — the one consistent indicator vocabulary for Seed Code.

Every screen that shows a status uses these markers so the language stays
uniform:

    ● Connected    ◐ Connecting    ○ Offline    ⚠ Error
    ⟳ Loading      ✓ Ready         ✗ Failed

Badges exist in two renderings: prompt_toolkit fragments (interactive
selectors) and Rich markup (panels, dashboard).
"""

from __future__ import annotations

from ..core.providers.base import (
    STATUS_BAD_KEY,
    STATUS_CONNECTED,
    STATUS_NO_KEY,
    STATUS_OFFLINE,
    STATUS_UNKNOWN,
)

# badge key -> (marker, label, pt style class, rich style)
BADGES: dict[str, tuple[str, str, str, str]] = {
    "connected": ("●", "Connected", "class:sel.ok", "seed.success"),
    "connecting": ("◐", "Connecting", "class:sel.warn", "seed.warning"),
    "offline": ("○", "Offline", "class:sel.off", "seed.dim"),
    "error": ("⚠", "Error", "class:sel.err", "seed.error"),
    "loading": ("⟳", "Loading", "class:sel.warn", "seed.warning"),
    "ready": ("✓", "Ready", "class:sel.ok", "seed.success"),
    "failed": ("✗", "Failed", "class:sel.err", "seed.error"),
}

# Provider session status -> badge key.
_STATUS_TO_BADGE = {
    STATUS_CONNECTED: "connected",
    STATUS_UNKNOWN: "ready",
    STATUS_OFFLINE: "offline",
    STATUS_NO_KEY: "offline",
    STATUS_BAD_KEY: "error",
}


def badge_for_status(status: str) -> str:
    """Map a provider connection status string to a badge key."""
    return _STATUS_TO_BADGE.get(status, "offline")


def badge_fragment(key: str) -> tuple[str, str]:
    """(pt style, text) for one badge, e.g. ('class:sel.ok', '● Connected')."""
    marker, label, style, _ = BADGES.get(key, BADGES["offline"])
    return style, f"{marker} {label}"


def badge_markup(key: str) -> str:
    """Rich markup for one badge, e.g. '[seed.success]● Connected[/]'."""
    marker, label, _, rich_style = BADGES.get(key, BADGES["offline"])
    return f"[{rich_style}]{marker} {label}[/{rich_style}]"


def badge_text(key: str) -> str:
    """Plain '● Connected' text for one badge."""
    marker, label, _, _ = BADGES.get(key, BADGES["offline"])
    return f"{marker} {label}"
