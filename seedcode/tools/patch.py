"""Patch tools: precise in-place edits by exact text matching.

``edit_file`` is the agent's scalpel — replace one exact occurrence of a
string — and ``insert_in_file`` adds a block before/after an exact anchor;
``write_file`` (filesystem) is the sledgehammer. Multi-file editing is
several edit/write calls in one turn; each passes the same permission gate
independently.

Matching happens on ``\\n``-normalized text (see :mod:`seedcode.tools.textio`)
and the original encoding/line endings are preserved on write, so editing a
CRLF or latin-1 file never silently converts it.

There is deliberately NO unified-diff applier here: model-generated diffs
malform often (line-number drift), which converts into retry loops that burn
the agent's step budget, while exact-match editing gives precise failure
messages the model can act on. edit_file + insert_in_file + write_file cover
every edit shape the loop needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ToolResult, register
from .textio import read_text_file, write_text_file

if TYPE_CHECKING:
    from .permissions import PermissionManager


@register(
    "edit_file",
    "Replace an exact text snippet in a file (must match exactly once).",
    {
        "path": "file path",
        "old_text": "exact text currently in the file",
        "new_text": "replacement text",
    },
    mutates=True,
)
def _edit_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    if not path.is_file():
        return ToolResult(False, f"File not found: {path}")

    old = str(args["old_text"]).replace("\r\n", "\n")
    new = str(args["new_text"]).replace("\r\n", "\n")
    if not old:
        return ToolResult(False, "old_text is empty — use write_file to create content.")
    if old == new:
        return ToolResult(False, "old_text and new_text are identical; nothing to do.")

    try:
        tf = read_text_file(path)
    except OSError as exc:
        return ToolResult(False, f"Could not read {path}: {exc}")

    count = tf.text.count(old)
    if count == 0:
        return ToolResult(
            False,
            f"old_text was not found in {path}. Read the file again and copy the "
            "text exactly (whitespace matters).",
        )
    if count > 1:
        return ToolResult(
            False,
            f"old_text appears {count} times in {path}. Include more surrounding "
            "lines so it matches exactly once.",
        )

    tf.text = tf.text.replace(old, new, 1)
    expected = tf.text
    try:
        write_text_file(path, tf)
    except OSError as exc:
        return ToolResult(False, f"Could not write {path}: {exc}")

    # VERIFICATION: the file must read back as exactly what we wrote
    # (comparing full text — substring checks false-positive when new_text
    # contains old_text, e.g. "b = 2" -> "b = 20").
    try:
        updated = read_text_file(path).text
        if updated != expected:
            return ToolResult(
                False,
                f"Edit operation completed but verification failed: {path} does "
                "not match the edited content. The file may have been modified "
                "by another process."
            )
    except OSError as exc:
        return ToolResult(
            False,
            f"Edit completed but verification failed: could not read back {path}: {exc}"
        )

    return ToolResult(True, f"Edited {path} (1 replacement, verified).")


@register(
    "insert_in_file",
    "Insert a block of text before or after an exact anchor snippet "
    "(anchor must match exactly once).",
    {
        "path": "file path",
        "anchor": "exact existing text to anchor on",
        "position": "'before' or 'after'",
        "text": "block to insert",
    },
    mutates=True,
)
def _insert_in_file(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    path = perm.resolve(args["path"])
    perm.check_write(path)
    if not path.is_file():
        return ToolResult(False, f"File not found: {path}")

    anchor = str(args["anchor"]).replace("\r\n", "\n")
    block = str(args["text"]).replace("\r\n", "\n")
    position = str(args["position"]).strip().lower()
    if position not in ("before", "after"):
        return ToolResult(False, "position must be 'before' or 'after'.")
    if not anchor:
        return ToolResult(False, "anchor is empty — copy an exact snippet from the file.")
    if not block:
        return ToolResult(False, "text is empty; nothing to insert.")

    try:
        tf = read_text_file(path)
    except OSError as exc:
        return ToolResult(False, f"Could not read {path}: {exc}")

    count = tf.text.count(anchor)
    if count == 0:
        return ToolResult(
            False,
            f"anchor was not found in {path}. Read the file again and copy the "
            "text exactly (whitespace matters).",
        )
    if count > 1:
        return ToolResult(
            False,
            f"anchor appears {count} times in {path}. Include more surrounding "
            "lines so it matches exactly once.",
        )

    replacement = block + anchor if position == "before" else anchor + block
    tf.text = tf.text.replace(anchor, replacement, 1)
    try:
        write_text_file(path, tf)
    except OSError as exc:
        return ToolResult(False, f"Could not write {path}: {exc}")

    # VERIFICATION: Read back to confirm the block landed where intended
    try:
        updated = read_text_file(path).text
        if replacement not in updated:
            return ToolResult(
                False,
                f"Insert completed but verification failed: the inserted block was "
                f"not found next to the anchor in {path}.",
            )
    except OSError as exc:
        return ToolResult(
            False,
            f"Insert completed but verification failed: could not read back {path}: {exc}"
        )

    return ToolResult(True, f"Inserted {len(block)} chars {position} the anchor in {path} (verified).")
