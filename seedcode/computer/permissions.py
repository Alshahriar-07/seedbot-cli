"""Desktop Control permission group: Y[once] / A[always] / N[deny] grants.

Filesystem permissions (see :mod:`seedcode.tools.permissions`) bound WHERE the
agent may act; this module bounds WHETHER it may touch the desktop at all.
Grants are per-category and session-only — nothing here is persisted, so a
fresh session always starts with a fresh ask. Sensitive categories (registry
writes, secrets, purchases, system power, deletions) can never be granted
"Always": they re-prompt on every single action by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from ..tools.permissions import PermissionError_


class DesktopGrant(str, Enum):
    ONCE = "once"
    ALWAYS = "always"
    DENY = "deny"


# Categories an action may fall into. `control` covers plain input and
# observation; the rest gate riskier ground.
CATEGORY_CONTROL = "control"          # mouse, keyboard, screenshots, window reads
CATEGORY_APPS = "apps"                # opening / closing applications
CATEGORY_REGISTRY_READ = "registry_read"

# Sensitive categories: confirmation can never be remembered ("Always" is
# treated as "Once"), so each individual action is user-approved.
CATEGORY_REGISTRY_WRITE = "registry_write"
CATEGORY_SECRET = "type_secret"       # typing passwords / credentials
CATEGORY_SYSTEM = "system"            # shutdown, restart, system settings
CATEGORY_DELETE = "delete"            # deleting files via the desktop
CATEGORY_PURCHASE = "purchase"        # browser purchases / payments

SENSITIVE_CATEGORIES = frozenset(
    {
        CATEGORY_REGISTRY_WRITE,
        CATEGORY_SECRET,
        CATEGORY_SYSTEM,
        CATEGORY_DELETE,
        CATEGORY_PURCHASE,
    }
)

CATEGORY_LABELS = {
    CATEGORY_CONTROL: "Desktop control (mouse, keyboard, screen)",
    CATEGORY_APPS: "Open / close applications",
    CATEGORY_REGISTRY_READ: "Read the Windows registry",
    CATEGORY_REGISTRY_WRITE: "WRITE to the Windows registry",
    CATEGORY_SECRET: "Type a password or secret",
    CATEGORY_SYSTEM: "System action (shutdown / restart / settings)",
    CATEGORY_DELETE: "Delete files via the desktop",
    CATEGORY_PURCHASE: "Browser purchase / payment",
}

# confirm(category, description) -> the user's choice for this ask.
ConfirmCallback = Callable[[str, str], DesktopGrant]


def _deny_all(category: str, description: str) -> DesktopGrant:
    """Default callback when no UI is wired: refuse everything."""
    return DesktopGrant.DENY


@dataclass
class DesktopSession:
    """Session-scoped Desktop Control gate consulted by every desktop tool.

    ``enabled`` mirrors ``config.desktop_mode``; ``confirm`` is wired to the
    UI prompt by the app layer. :meth:`check` either returns silently or
    raises :class:`PermissionError_` with text the model can act on.
    """

    enabled: bool = False
    confirm: ConfirmCallback = _deny_all
    grants: dict[str, DesktopGrant] = field(default_factory=dict)
    # Base64 PNG screenshots queued by observation tools; the agent loop
    # drains this and attaches images when the provider supports vision.
    pending_images: list[str] = field(default_factory=list)

    def check(self, category: str, description: str) -> None:
        """Gate one desktop action; raises PermissionError_ when refused."""
        if not self.enabled:
            raise PermissionError_(
                "Blocked: desktop mode is off. The user can enable it with /desktop on."
            )

        sensitive = category in SENSITIVE_CATEGORIES
        if not sensitive:
            granted = self.grants.get(category)
            if granted is DesktopGrant.ALWAYS:
                return
            if granted is DesktopGrant.DENY:
                raise PermissionError_(
                    f"Blocked: the user denied '{CATEGORY_LABELS.get(category, category)}' "
                    "for this session."
                )

        choice = self.confirm(category, description)
        if sensitive and choice is DesktopGrant.ALWAYS:
            # Sensitive actions are approved one at a time, never blanket.
            choice = DesktopGrant.ONCE
        if not sensitive and choice in (DesktopGrant.ALWAYS, DesktopGrant.DENY):
            self.grants[category] = choice
        if choice is DesktopGrant.DENY:
            raise PermissionError_(
                f"Blocked: the user denied this action ({description})."
            )

    def reset(self) -> None:
        """Forget all session grants (used when desktop mode toggles)."""
        self.grants.clear()
        self.pending_images.clear()
