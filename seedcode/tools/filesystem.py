"""Filesystem tools: read, write, list, delete — plus the project indexer.

Multi-file editing is simply several ``write_file``/``edit_file`` calls in one
agent turn; each one passes the same permission gate. The indexer produces a
compact tree of the workspace so the model can orient itself without reading
every file.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import ToolResult, int_arg, register
from .permissions import CATEGORY_DELETE
from .textio import TextFile, read_text_file, write_text_file

if TYPE_CHECKING:
    from .permissions import PermissionManager

# Read caps: a tool call must never dump a huge binary/log into the context.
_MAX_READ_BYTES = 256 * 1024
_MAX_INDEX_ENTRIES = 400

# Directories that never belong in a project index.
_INDEX_SKIP = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
}


@register(
    "read_file",
    "Read a text file (optionally a line range).",
    {
        "path": "file path",
        "start_line": "(optional) first line, 1-based",
        "end_line": "(optional) last line, inclusive",
    },
    mutates=False,
    types={"start_line": "integer", "end_line": "integer"},
)
def _read_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_read(path)
    if not path.is_file():
        return ToolResult(False, f"File not found: {path}")
    if path.stat().st_size > _MAX_READ_BYTES and "start_line" not in args:
        return ToolResult(
            False,
            f"File is large ({path.stat().st_size} bytes). "
            "Read it in ranges with start_line/end_line.",
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ToolResult(False, f"Could not read {path}: {exc}")

    lines = text.splitlines()
    start = int_arg(args, "start_line", 1, 1, 10_000_000)
    end = min(len(lines), int_arg(args, "end_line", len(lines), 0, 10_000_000))
    numbered = [f"{i}\t{lines[i - 1]}" for i in range(start, end + 1)]
    header = f"{path} ({len(lines)} lines, showing {start}-{end})"
    return ToolResult(True, header + "\n" + "\n".join(numbered))


@register(
    "write_file",
    "Create or overwrite a file with the given content.",
    {"path": "file path", "content": "full new file content"},
    mutates=True,
)
def _write_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    content = str(args["content"])

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(False, f"Could not write {path}: {exc}")

    # VERIFICATION: Read back to confirm write succeeded
    try:
        written = path.read_text(encoding="utf-8", errors="replace")
        if written != content:
            return ToolResult(
                False,
                f"Verification failed: {path} was written but content doesn't match. "
                f"Expected {len(content)} chars, read back {len(written)} chars."
            )
    except OSError as exc:
        return ToolResult(
            False,
            f"Write completed but verification failed: could not read {path}: {exc}"
        )

    return ToolResult(True, f"Wrote {len(content)} chars to {path} (verified)")


@register(
    "delete_file",
    "Delete a single file (never a directory).",
    {"path": "file path"},
    mutates=True,
)
def _delete_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    if path.is_dir():
        return ToolResult(False, f"Refusing to delete a directory: {path}")
    if not path.exists():
        return ToolResult(False, f"File not found: {path}")
    perm.confirm_action(CATEGORY_DELETE, str(path))
    try:
        path.unlink()
    except OSError as exc:
        return ToolResult(False, f"Could not delete {path}: {exc}")

    # VERIFICATION: Confirm file no longer exists
    if path.exists():
        return ToolResult(
            False,
            f"Delete command completed but {path} still exists. Possible permission or filesystem issue."
        )

    return ToolResult(True, f"Deleted {path} (verified)")


@register(
    "list_dir",
    "List the entries of a directory.",
    {"path": "(optional) directory path, defaults to the workspace root"},
    mutates=False,
)
def _list_dir(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args.get("path") or ".")
    perm.check_read(path)
    if not path.is_dir():
        return ToolResult(False, f"Not a directory: {path}")
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return ToolResult(False, f"Could not list {path}: {exc}")
    lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries]
    return ToolResult(True, f"{path}\n" + ("\n".join(lines) or "(empty)"))


@register(
    "append_file",
    "Append content to the end of a file (created if missing).",
    {"path": "file path", "content": "text to append"},
    mutates=True,
)
def _append_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    content = str(args["content"])
    if not content:
        return ToolResult(False, "content is empty; nothing to append.")

    try:
        if path.is_file():
            tf = read_text_file(path)  # preserve encoding + line endings
            tf.text += content.replace("\r\n", "\n")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tf = TextFile(text=content.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        write_text_file(path, tf)
    except OSError as exc:
        return ToolResult(False, f"Could not append to {path}: {exc}")

    # VERIFICATION: the appended text must be at the end of the file
    try:
        if not read_text_file(path).text.endswith(content.replace("\r\n", "\n")):
            return ToolResult(
                False,
                f"Append completed but verification failed: {path} does not end "
                "with the appended text.",
            )
    except OSError as exc:
        return ToolResult(
            False, f"Append completed but verification failed: could not read {path}: {exc}"
        )

    return ToolResult(True, f"Appended {len(content)} chars to {path} (verified)")


@register(
    "create_directory",
    "Create a directory (parents included).",
    {"path": "directory path"},
    mutates=True,
)
def _create_directory(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    if path.is_file():
        return ToolResult(False, f"A file already exists at {path}.")
    existed = path.is_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolResult(False, f"Could not create directory {path}: {exc}")
    if not path.is_dir():
        return ToolResult(False, f"mkdir completed but {path} does not exist.")
    return ToolResult(True, f"Directory {'already existed' if existed else 'created'}: {path}")


@register(
    "rename_file",
    "Rename a file within its directory (use move_file to change directories).",
    {"path": "current file path", "new_name": "new file name (no directories)"},
    mutates=True,
)
def _rename_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    new_name = str(args["new_name"]).strip()
    if not new_name or any(sep in new_name for sep in ("/", "\\")):
        return ToolResult(
            False, "new_name must be a bare file name — use move_file to change directories."
        )
    target = path.with_name(new_name)
    perm.check_write(path)
    perm.check_write(target)
    if not path.exists():
        return ToolResult(False, f"File not found: {path}")
    if target.exists():
        return ToolResult(False, f"Refusing to overwrite existing {target}.")
    try:
        path.rename(target)
    except OSError as exc:
        return ToolResult(False, f"Could not rename {path}: {exc}")
    if not target.exists() or path.exists():
        return ToolResult(False, f"Rename completed but verification failed for {target}.")
    return ToolResult(True, f"Renamed {path} -> {target} (verified)")


@register(
    "move_file",
    "Move a file to another path (directories created as needed).",
    {"path": "current file path", "destination": "new file path"},
    mutates=True,
)
def _move_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    target = perm.resolve(args["destination"])
    perm.check_write(path)
    perm.check_write(target)  # outside-workspace destinations hit the gate
    if not path.exists():
        return ToolResult(False, f"File not found: {path}")
    if path.is_dir():
        return ToolResult(False, f"Refusing to move a directory: {path}")
    if target.is_dir():
        target = target / path.name
    if target.exists():
        return ToolResult(False, f"Refusing to overwrite existing {target}.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))  # handles cross-drive on Windows
    except OSError as exc:
        return ToolResult(False, f"Could not move {path}: {exc}")
    if not target.exists() or path.exists():
        return ToolResult(False, f"Move completed but verification failed for {target}.")
    return ToolResult(True, f"Moved {path} -> {target} (verified)")


def _walk_index(root: Path, prefix: str, lines: list[str]) -> None:
    """Depth-first tree walk, capped at _MAX_INDEX_ENTRIES lines."""
    if len(lines) >= _MAX_INDEX_ENTRIES:
        return
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return
    for entry in entries:
        if len(lines) >= _MAX_INDEX_ENTRIES:
            lines.append(f"{prefix}... (index capped at {_MAX_INDEX_ENTRIES} entries)")
            return
        if entry.name in _INDEX_SKIP or entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"{prefix}{entry.name}/")
            _walk_index(entry, prefix + "  ", lines)
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            lines.append(f"{prefix}{entry.name}  ({size} B)")


def build_index(perm: "PermissionManager") -> str:
    """Compact workspace tree (shared by the tool and the /index command)."""
    lines: list[str] = [f"{perm.workspace}/"]
    _walk_index(perm.workspace, "  ", lines)
    return "\n".join(lines)


@register(
    "project_index",
    "Get a compact tree of the whole workspace (files, sizes).",
    {},
    mutates=False,
)
def _project_index(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return ToolResult(True, build_index(perm))
