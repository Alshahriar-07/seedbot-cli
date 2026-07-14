"""Live streaming markdown renderer.

Accumulates streamed tokens and re-renders them as live markdown so code blocks
and formatting appear as the assistant types.
"""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown


class StreamRenderer:
    """Accumulates streamed tokens and re-renders them as live markdown."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._buffer = ""
        self._live: Live | None = None

    def bind(self, live: Live) -> None:
        self._live = live

    def renderable(self):
        # Assistant output rendered as markdown for code blocks and formatting.
        return Markdown(self._buffer or "", code_theme="ansi_dark")

    def feed(self, chunk: str) -> None:
        self._buffer += chunk
        if self._live is not None:
            self._live.update(self.renderable())

    @property
    def text(self) -> str:
        return self._buffer
