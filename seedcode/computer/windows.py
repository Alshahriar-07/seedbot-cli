"""Window management driver: list, focus, open, and close applications.

Window enumeration and focus use ``pygetwindow`` (Win32 under the hood).
Opening applications goes through ``os.startfile``/``start`` semantics so
anything resolvable by the shell (path, registered app, document) works.
Closing is graceful first (WM_CLOSE) with a ``taskkill`` fallback by name.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class WindowInfo:
    """One top-level window as reported to the model."""

    title: str
    left: int
    top: int
    width: int
    height: int
    active: bool
    minimized: bool

    def describe(self) -> str:
        state = "active" if self.active else ("minimized" if self.minimized else "open")
        return (
            f'"{self.title}" [{state}] at ({self.left}, {self.top}) '
            f"size {self.width}x{self.height}"
        )


def _gw():
    import pygetwindow

    return pygetwindow


def list_windows() -> list[WindowInfo]:
    """All titled top-level windows, active one first."""
    gw = _gw()
    active = gw.getActiveWindow()
    active_handle = getattr(active, "_hWnd", None)
    windows = []
    for win in gw.getAllWindows():
        if not (win.title or "").strip():
            continue
        windows.append(
            WindowInfo(
                title=win.title,
                left=int(win.left),
                top=int(win.top),
                width=int(win.width),
                height=int(win.height),
                active=getattr(win, "_hWnd", None) == active_handle,
                minimized=bool(win.isMinimized),
            )
        )
    windows.sort(key=lambda w: not w.active)
    return windows


def active_window() -> WindowInfo | None:
    """The focused window, or None when nothing is focused."""
    win = _gw().getActiveWindow()
    if win is None or not (win.title or "").strip():
        return None
    return WindowInfo(
        title=win.title,
        left=int(win.left),
        top=int(win.top),
        width=int(win.width),
        height=int(win.height),
        active=True,
        minimized=bool(win.isMinimized),
    )


def _find(title_substring: str):
    """First window whose title contains ``title_substring`` (case-insensitive)."""
    needle = title_substring.strip().lower()
    if not needle:
        raise ValueError("Window title (or part of it) is required.")
    for win in _gw().getAllWindows():
        if needle in (win.title or "").lower():
            return win
    raise ValueError(f"No window found matching '{title_substring}'.")


def focus_window(title_substring: str) -> WindowInfo | None:
    """Bring a window to the foreground; returns the new active window."""
    win = _find(title_substring)
    if win.isMinimized:
        win.restore()
    win.activate()
    return active_window()


def open_app(target: str) -> str:
    """Launch an application or open a document via the shell.

    ``target`` is anything the Windows shell can resolve: an exe name on
    PATH, a full path, or a registered app (e.g. "notepad", "calc").
    ShellExecute via ``os.startfile`` first (documents, App Paths), then a
    detached ``start`` as fallback — never waiting on the launched process,
    which would hang until the app exits.
    """
    import os

    target = target.strip()
    if not target:
        raise ValueError("Application name or path is required.")
    try:
        os.startfile(target)  # noqa: S606 - deliberate shell-open semantics
        return f"Launched '{target}'."
    except OSError:
        pass
    # Fallback: 'start' resolves PATH executables and shell aliases. The
    # process is detached (no inherited pipes) so this returns immediately.
    try:
        subprocess.Popen(
            f'start "" "{target}"',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not open '{target}': {exc}")
    return f"Launched '{target}'."


def close_window(title_substring: str, force: bool = False) -> str:
    """Close a window gracefully (WM_CLOSE); ``force`` kills the process."""
    win = _find(title_substring)
    title = win.title
    win.close()
    if force:
        # Best-effort process kill for apps that ignore WM_CLOSE.
        subprocess.run(
            f'taskkill /FI "WINDOWTITLE eq {title}*" /F',
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    return f"Closed '{title}'."
