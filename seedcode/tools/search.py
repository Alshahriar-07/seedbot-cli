"""Search tools: filename glob and text search across the workspace.

Pure-Python (pathlib + a linear scan) so search works identically on Windows,
Linux, and macOS with no external binaries.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import ToolResult, register
from .filesystem import _INDEX_SKIP

if TYPE_CHECKING:
    from .permissions import PermissionManager

_MAX_MATCHES = 100
_MAX_FILE_BYTES = 1024 * 1024  # skip anything bigger — likely binary/asset


def _iter_files(root: Path):
    """Workspace files, skipping caches/VCS dirs and hidden entries."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.name in _INDEX_SKIP or entry.name.startswith("."):
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield entry


def _glob_to_regex(pattern: str) -> "re.Pattern[str]":
    """Compile a path glob ('src/**/*.py') to a regex over posix paths.

    ``**/`` matches any directory depth (including none), ``**`` any run of
    characters, ``*`` within one segment, ``?`` one character.
    (``PurePath.full_match`` needs Python 3.13; this supports 3.10+.)
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append(r"(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(r".*")
            i += 2
        elif ch == "*":
            out.append(r"[^/]*")
            i += 1
        elif ch == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out) + r"\Z")


@register(
    "find_files",
    "Find files by glob: a name pattern ('*.py') or a path pattern "
    "('src/**/*.py', relative to the workspace).",
    {"pattern": "glob matched against file names, or paths when it contains '/'"},
    mutates=False,
)
def _find_files(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    pattern = str(args["pattern"]).replace("\\", "/")
    path_mode = "/" in pattern
    path_regex = _glob_to_regex(pattern) if path_mode else None

    matches = []
    for path in _iter_files(perm.workspace):
        if path_mode:
            rel = path.relative_to(perm.workspace).as_posix()
            matched = path_regex.match(rel) is not None
        else:
            matched = fnmatch.fnmatch(path.name, pattern)
        if matched:
            matches.append(str(path.relative_to(perm.workspace)))
            if len(matches) >= _MAX_MATCHES:
                matches.append(f"... (capped at {_MAX_MATCHES})")
                break
    if not matches:
        return ToolResult(True, f"No files matching '{pattern}'.")
    return ToolResult(True, "\n".join(matches))


@register(
    "search_text",
    "Search file contents for a regex; returns file:line matches.",
    {
        "pattern": "regular expression",
        "glob": "(optional) only search files whose name matches this glob",
    },
    mutates=False,
)
def _search_text(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    try:
        regex = re.compile(str(args["pattern"]))
    except re.error as exc:
        return ToolResult(False, f"Invalid regex: {exc}")
    name_glob = str(args.get("glob") or "*")

    hits: list[str] = []
    for path in _iter_files(perm.workspace):
        if not fnmatch.fnmatch(path.name, name_glob):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text[:1024]:  # binary sniff
            continue
        rel = path.relative_to(perm.workspace)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                if len(hits) >= _MAX_MATCHES:
                    hits.append(f"... (capped at {_MAX_MATCHES})")
                    return ToolResult(True, "\n".join(hits))
    if not hits:
        return ToolResult(True, f"No matches for '{args['pattern']}'.")
    return ToolResult(True, "\n".join(hits))
