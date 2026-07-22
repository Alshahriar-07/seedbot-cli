"""Computer Engine execution state.

The engine keeps its own memory of the machine so the AI never has to re-ask
for it: what app is focused, where the pointer is, what's on the clipboard,
which directory the terminal is in, and a short trail of the last actions. The
:class:`StateManager` refreshes the live parts (focused window, pointer) on
demand from the drivers and records the rest as the dispatcher executes skills.

This module is deterministic and offline — it only reads driver state and holds
values; it never talks to an AI provider.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Keep the action trail short; it exists to give the AI recent context, not a
# full audit log (that's the logbook's job).
_MAX_TRAIL = 12


@dataclass
class ComputerState:
    """A snapshot of what the Computer Engine believes about the machine."""

    focused_window: str | None = None
    focused_app: str | None = None
    pointer: tuple[int, int] | None = None
    clipboard_preview: str | None = None
    terminal_cwd: str | None = None
    current_project: str | None = None
    open_browser_url: str | None = None
    modifiers_held: tuple[str, ...] = ()
    recent_actions: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """Compact, model-facing rendering of the current state."""
        rows: list[tuple[str, str]] = []
        if self.focused_app:
            rows.append(("app", self.focused_app))
        if self.focused_window:
            rows.append(("window", self.focused_window))
        if self.pointer is not None:
            rows.append(("pointer", f"({self.pointer[0]}, {self.pointer[1]})"))
        if self.clipboard_preview:
            rows.append(("clipboard", self.clipboard_preview))
        if self.terminal_cwd:
            rows.append(("terminal", self.terminal_cwd))
        if self.current_project:
            rows.append(("project", self.current_project))
        if self.open_browser_url:
            rows.append(("browser", self.open_browser_url))
        if self.modifiers_held:
            rows.append(("modifiers", "+".join(self.modifiers_held)))
        if not rows and not self.recent_actions:
            return "Computer state: (nothing observed yet)"
        lines = ["Computer state:"]
        lines += [f"  {label}: {value}" for label, value in rows]
        if self.recent_actions:
            lines.append("  recent:")
            lines += [f"    - {a}" for a in self.recent_actions[-5:]]
        return "\n".join(lines)


class StateManager:
    """Owns the engine's :class:`ComputerState` and keeps it fresh.

    The live bits (focused window, pointer position) are pulled from the driver
    modules on :meth:`refresh`; everything else is recorded by the dispatcher as
    skills run so the AI gets continuity across steps for free.
    """

    def __init__(self, windows: Any = None, mouse: Any = None) -> None:
        # Drivers are injectable so tests can drive the manager without a real
        # desktop; lazy-imported here to keep import order clean off-win32.
        if windows is None:
            from . import windows as windows  # type: ignore
        if mouse is None:
            from . import mouse as mouse  # type: ignore
        self._windows = windows
        self._mouse = mouse
        self.state = ComputerState()

    def refresh(self) -> ComputerState:
        """Re-read the live parts of the state from the drivers.

        Best-effort: a driver that raises (no desktop, flaky COM) leaves the
        previous value in place rather than crashing the turn.
        """
        try:
            active = self._windows.active_window()
            if active is not None:
                self.state.focused_window = active.title or None
                self.state.focused_app = _app_from_title(active.title)
        except Exception:
            pass
        try:
            pos = self._mouse.position()
            if pos is not None:
                self.state.pointer = (int(pos[0]), int(pos[1]))
        except Exception:
            pass
        return self.state

    # --- recording (called by the dispatcher / skills) ----------------------
    def record_action(self, description: str) -> None:
        trail = self.state.recent_actions
        trail.append(description)
        if len(trail) > _MAX_TRAIL:
            del trail[: len(trail) - _MAX_TRAIL]

    def set_clipboard(self, text: str | None) -> None:
        if not text:
            self.state.clipboard_preview = None
        else:
            preview = text.strip().replace("\n", " ")
            self.state.clipboard_preview = preview[:60] + ("…" if len(preview) > 60 else "")

    def set_terminal_cwd(self, cwd: str | None) -> None:
        self.state.terminal_cwd = cwd

    def set_project(self, project: str | None) -> None:
        self.state.current_project = project

    def set_browser_url(self, url: str | None) -> None:
        self.state.open_browser_url = url

    def note_focus(self, window_title: str | None) -> None:
        """Record a focus change the driver just performed."""
        if window_title:
            self.state.focused_window = window_title
            self.state.focused_app = _app_from_title(window_title)


def _app_from_title(title: str | None) -> str | None:
    """Best-effort app name from a window title.

    Windows titles are usually ``Document — App`` or ``Document - App``; the
    trailing segment is the app. Falls back to the whole title.
    """
    if not title:
        return None
    for sep in (" — ", " - ", " – "):
        if sep in title:
            return title.rsplit(sep, 1)[-1].strip() or title.strip()
    return title.strip()
