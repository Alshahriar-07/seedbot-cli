"""Encoding- and newline-preserving text file I/O for edit-path tools.

Editing a latin-1 or CRLF file must not silently convert it to UTF-8/LF —
that corrupts files the user never asked to touch. Every tool that edits an
EXISTING file reads it through :func:`read_text_file` (which remembers the
encoding and dominant newline) and writes it back through
:func:`write_text_file` (which re-applies both). Matching and editing happen
on ``\\n``-normalized text, so tools never worry about CRLF.

Decoding order: UTF-8 with BOM ("utf-8-sig"), then strict UTF-8, then
latin-1 (which cannot fail — every byte is valid — so nothing is ever lossy
on the read side).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TextFile:
    """A decoded text file: normalized text plus how to write it back."""

    text: str       # normalized to \n line endings
    encoding: str   # "utf-8-sig" | "utf-8" | "latin-1"
    newline: str    # "\r\n" | "\n"


def read_text_file(path: Path) -> TextFile:
    """Read and decode, remembering encoding and dominant newline.

    Raises OSError on filesystem problems (callers turn that into a
    friendly ToolResult).
    """
    raw = path.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
            encoding = "latin-1"

    crlf = text.count("\r\n")
    bare_lf = text.count("\n") - crlf
    newline = "\r\n" if crlf > bare_lf else "\n"

    return TextFile(text=text.replace("\r\n", "\n"), encoding=encoding, newline=newline)


def write_text_file(path: Path, tf: TextFile) -> None:
    """Write normalized text back with the original newline and encoding."""
    text = tf.text.replace("\n", tf.newline) if tf.newline != "\n" else tf.text
    path.write_bytes(text.encode(tf.encoding))
