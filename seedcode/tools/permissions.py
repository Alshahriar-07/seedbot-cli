"""Unified permission system for Seed Code.

A single hierarchical :class:`PermissionLevel` is the one source of truth for
what the session may do, checked before every privileged operation:

* ``read_only``    — inspect only: no writes, no commands, no git mutations,
                     no desktop control.
* ``workspace``    — read anywhere, mutate only inside the workspace directory
                     (the directory Seed Code was started in); still no desktop.
* ``desktop``      — everything ``workspace`` allows, plus control of the local
                     computer through the Computer Engine (mouse, keyboard,
                     windows, apps, browser, non-sensitive registry reads).
* ``full_system``  — no path restriction on mutations and sensitive desktop
                     actions (registry writes, secrets, system power, deletes,
                     purchases) become available (still confirmed per action).

Levels are ordered (``READ_ONLY < WORKSPACE < DESKTOP < FULL_SYSTEM``) so a
capability check is a single comparison: ``level >= required``. Desktop
automation is a *capability of a level*, not a separate mode — the old
``desktop_mode`` flag is gone.

On top of the levels, *dangerous* actions (shell commands, file deletes, git
mutations, writes outside the workspace, and every sensitive desktop action)
ask the user first — the Y/A/N prompt is [Y] once / [A] always for this
session / [N] cancel. "Always"/"Deny" answers are remembered per category for
the session only, never persisted; sensitive categories never remember.

The manager is the single gate: tools never check paths or levels themselves,
they ask :meth:`PermissionManager.require` / :meth:`check_read` /
:meth:`check_write` / :meth:`check_execute` / :meth:`confirm_action` and let
the raised error flow back to the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..computer.permissions import DesktopSession


class PermissionError_(Exception):
    """An action was blocked by the current permission level.

    Named with a trailing underscore to avoid shadowing the builtin
    ``PermissionError`` (raised by the OS for filesystem denials).
    """


class PermissionLevel(IntEnum):
    """Hierarchical capability level; higher includes everything lower."""

    READ_ONLY = 0
    WORKSPACE = 1
    DESKTOP = 2
    FULL_SYSTEM = 3
    # Legacy alias: pre-vNext configs used "full_access" for the top level.
    FULL_ACCESS = 3

    @classmethod
    def parse(cls, value: "str | PermissionLevel") -> "PermissionLevel":
        if isinstance(value, PermissionLevel):
            return value
        raw = (str(value) or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "read": cls.READ_ONLY,
            "readonly": cls.READ_ONLY,
            "read_only": cls.READ_ONLY,
            "ws": cls.WORKSPACE,
            "workspace": cls.WORKSPACE,
            "desktop": cls.DESKTOP,
            "computer": cls.DESKTOP,
            "full": cls.FULL_SYSTEM,
            "full_access": cls.FULL_SYSTEM,
            "fullaccess": cls.FULL_SYSTEM,
            "full_system": cls.FULL_SYSTEM,
            "fullsystem": cls.FULL_SYSTEM,
            "system": cls.FULL_SYSTEM,
        }
        level = aliases.get(raw)
        if level is None:
            raise ValueError(
                f"Unknown permission level '{value}'. "
                "Choose read_only, workspace, desktop, or full_system."
            )
        return level

    @property
    def value_str(self) -> str:
        """Canonical serialised name for this level."""
        return {
            PermissionLevel.READ_ONLY: "read_only",
            PermissionLevel.WORKSPACE: "workspace",
            PermissionLevel.DESKTOP: "desktop",
            PermissionLevel.FULL_SYSTEM: "full_system",
        }[PermissionLevel(int(self))]

    @property
    def label(self) -> str:
        return {
            PermissionLevel.READ_ONLY: "Read Only",
            PermissionLevel.WORKSPACE: "Workspace",
            PermissionLevel.DESKTOP: "Desktop",
            PermissionLevel.FULL_SYSTEM: "Full System",
        }[PermissionLevel(int(self))]

    @property
    def allows_desktop(self) -> bool:
        """Whether this level may drive the Computer Engine at all."""
        return int(self) >= int(PermissionLevel.DESKTOP)


# Backward-compatible name: older modules import ``PermissionMode`` and
# reference ``PermissionMode.FULL_ACCESS``. Both resolve through the unified
# enum now, so a single class serves every caller.
PermissionMode = PermissionLevel


class ActionGrant(str, Enum):
    """The user's answer to a dangerous-action prompt."""

    ONCE = "once"
    ALWAYS = "always"
    DENY = "deny"


# Dangerous-action categories. Grants are remembered per category for the
# session; the descriptions shown to the user always include the concrete
# action (the exact command / path / git args).
CATEGORY_SHELL = "shell"                  # run a terminal command
CATEGORY_GIT_MUTATE = "git_mutate"        # commit / merge / reset / ...
CATEGORY_GIT_REMOTE = "git_remote"        # push / pull / fetch
CATEGORY_DELETE = "delete"                # delete a file
CATEGORY_OUTSIDE_WRITE = "outside_write"  # write outside the workspace

ACTION_LABELS = {
    CATEGORY_SHELL: "Run a shell command",
    CATEGORY_GIT_MUTATE: "Change git state",
    CATEGORY_GIT_REMOTE: "Talk to a git remote",
    CATEGORY_DELETE: "Delete a file",
    CATEGORY_OUTSIDE_WRITE: "Write outside the workspace",
}

# (category, description) -> the user's grant.
ConfirmAction = Callable[[str, str], "ActionGrant"]


@dataclass
class ActionGate:
    """Session-scoped Y/A/N confirmation for dangerous core-tool actions.

    The app layer supplies ``confirm`` (wired to the UI prompt); "Always" and
    "Deny" answers stick for the rest of the session, "Once" asks again next
    time. Nothing is ever persisted.
    """

    confirm: ConfirmAction
    grants: dict[str, "ActionGrant"] = field(default_factory=dict)

    def check(self, category: str, description: str) -> None:
        granted = self.grants.get(category)
        if granted is ActionGrant.ALWAYS:
            return
        if granted is ActionGrant.DENY:
            label = ACTION_LABELS.get(category, category)
            raise PermissionError_(
                f"Blocked: the user denied '{label}' for this session."
            )
        choice = self.confirm(category, description)
        if choice in (ActionGrant.ALWAYS, ActionGrant.DENY):
            self.grants[category] = choice
        if choice is ActionGrant.DENY:
            raise PermissionError_(
                f"Blocked: the user denied this action ({description})."
            )

    def reset(self) -> None:
        """Forget all session grants."""
        self.grants.clear()


class PermissionManager:
    """Gatekeeper consulted by every tool before acting."""

    def __init__(
        self,
        workspace: Path | None = None,
        mode: "PermissionLevel | str" = PermissionLevel.WORKSPACE,
        level: "PermissionLevel | str | None" = None,
    ) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        # ``level`` is the canonical field; ``mode`` is accepted as the legacy
        # keyword and both stay in sync through the ``mode`` property below.
        self.level = PermissionLevel.parse(level if level is not None else mode)
        # Desktop Control gate (the Computer Engine); attached by the app layer
        # when the level allows desktop. None means desktop tools refuse.
        self.desktop: "DesktopSession | None" = None
        # Dangerous-action confirmation gate; attached by the app layer. None
        # means no prompting (headless/tests) — the level checks alone decide.
        self.gate: ActionGate | None = None
        # Live command output sink (attached by the app layer): each line a
        # running terminal command prints is echoed here as it arrives.
        self.on_output: Callable[[str], None] | None = None

    # --- level (with legacy ``mode`` alias) ----------------------------------
    @property
    def mode(self) -> PermissionLevel:
        """Legacy alias for :attr:`level` (same object)."""
        return self.level

    @mode.setter
    def mode(self, value: "PermissionLevel | str") -> None:
        self.level = PermissionLevel.parse(value)

    def require(self, required: "PermissionLevel | str", description: str = "") -> None:
        """Raise unless the current level meets ``required``.

        The single capability gate the Computer Engine and every privileged
        tool consults. Elevation prompting is handled by the app layer (which
        may raise the level in response); this method only enforces the
        current level.
        """
        needed = PermissionLevel.parse(required)
        if self.level >= needed:
            return
        what = f" ({description})" if description else ""
        raise PermissionError_(
            f"Blocked: this needs {needed.label} permission{what}, but the "
            f"current level is {self.level.label}. The user can raise it with "
            "/permission."
        )

    # --- path helpers --------------------------------------------------------
    def resolve(self, raw: str) -> Path:
        """Resolve a tool-supplied path (relative paths anchor at the workspace)."""
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def in_workspace(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False

    # --- checks (raise PermissionError_ when blocked) -------------------------
    def check_read(self, path: Path) -> None:
        """Reading is allowed at every level."""

    def check_write(self, path: Path) -> None:
        if self.level < PermissionLevel.WORKSPACE:
            raise PermissionError_(
                "Blocked: permission level is Read Only — no file changes allowed. "
                "The user can raise it with /permission."
            )
        if self.level < PermissionLevel.FULL_SYSTEM and not self.in_workspace(path):
            raise PermissionError_(
                f"Blocked: '{path}' is outside the workspace ({self.workspace}). "
                "Only Full System allows changes outside it — "
                "the user can raise it with /permission full_system."
            )
        if self.level >= PermissionLevel.FULL_SYSTEM and not self.in_workspace(path):
            # Full System allows it, but writing outside the workspace is
            # dangerous enough to confirm with the user first.
            self.confirm_action(CATEGORY_OUTSIDE_WRITE, str(path))

    def check_execute(self, description: str = "") -> None:
        """Commands and git mutations need more than Read Only."""
        if self.level < PermissionLevel.WORKSPACE:
            what = f" ({description})" if description else ""
            raise PermissionError_(
                f"Blocked: permission level is Read Only — cannot execute{what}. "
                "The user can raise it with /permission."
            )

    def confirm_action(self, category: str, description: str) -> None:
        """Ask the user to confirm a dangerous action (no-op without a gate).

        Raises :class:`PermissionError_` when the user denies; the message
        flows back to the model like any other permission refusal.
        """
        if self.gate is not None:
            self.gate.check(category, description)
