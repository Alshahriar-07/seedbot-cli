"""Git integration tool: a safe subset of git run inside the workspace.

Read subcommands (status, log, diff, ...) work in every permission mode;
mutating ones (add, commit, checkout, ...) pass the execute gate AND the
user's Y/A/N confirmation, and remote ones (push, pull, fetch) get their own
confirmation category — Seed Code never commits or pushes silently. Anything
outside the allow-list is refused so the model cannot smuggle arbitrary
commands through the git tool (it must use run_command, which is gated too).
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from .base import ToolResult, register
from .permissions import CATEGORY_GIT_MUTATE, CATEGORY_GIT_REMOTE
from .terminal import run_command

if TYPE_CHECKING:
    from .permissions import PermissionManager

_READ_SUBCOMMANDS = {"status", "log", "diff", "show", "branch", "remote", "blame", "shortlog"}
_WRITE_SUBCOMMANDS = {
    "add", "commit", "checkout", "switch", "restore", "stash",
    "merge", "rebase", "reset", "revert", "init", "tag", "rm", "mv",
}
_REMOTE_SUBCOMMANDS = {"push", "pull", "fetch"}
_GIT_TIMEOUT_S = 60


@register(
    "git",
    "Run a git subcommand in the workspace (status, log, diff, add, commit, push, pull, ...).",
    {"args": "git arguments, e.g. 'status' or 'commit -m \"message\"'"},
    mutates=True,
)
def _git(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    raw = str(args["args"]).strip()
    if raw.startswith("git "):
        raw = raw[4:]  # tolerate "git status" as well as "status"
    if not raw:
        return ToolResult(False, "No git subcommand given.")

    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        return ToolResult(False, f"Could not parse git arguments: {exc}")
    sub = parts[0].lower() if parts else ""

    if sub in _WRITE_SUBCOMMANDS:
        perm.check_execute(f"git {sub}")
        perm.confirm_action(CATEGORY_GIT_MUTATE, f"git {raw}")
    elif sub in _REMOTE_SUBCOMMANDS:
        perm.check_execute(f"git {sub}")
        perm.confirm_action(CATEGORY_GIT_REMOTE, f"git {raw}")
    elif sub not in _READ_SUBCOMMANDS:
        allowed = ", ".join(
            sorted(_READ_SUBCOMMANDS | _WRITE_SUBCOMMANDS | _REMOTE_SUBCOMMANDS)
        )
        return ToolResult(False, f"git subcommand '{sub}' is not allowed. Allowed: {allowed}.")

    # shlex.split validated the quoting; re-quote for the real shell.
    quoted = " ".join(_quote(p) for p in parts)
    return run_command(perm, f"git {quoted}", _GIT_TIMEOUT_S)


def _quote(part: str) -> str:
    """Minimal cross-platform quoting (shlex.quote is POSIX-only)."""
    if part and all(c.isalnum() or c in "-_=./:@^~+%," for c in part):
        return part
    return '"' + part.replace('"', '\\"') + '"'
