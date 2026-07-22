"""Mouse driver: move, click, drag, scroll via pyautogui.

Coordinate validation lives in the controller (which knows the screen
geometry); this module only performs the raw actions. ``FAILSAFE`` stays on:
slamming the pointer into the top-left corner aborts any action — the user's
emergency brake.
"""

from __future__ import annotations


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05  # small settle between low-level actions
    return pyautogui


def position() -> tuple[int, int]:
    """Current pointer position."""
    point = _pyautogui().position()
    return int(point.x), int(point.y)


def move(x: int, y: int, duration: float = 0.2) -> None:
    _pyautogui().moveTo(x, y, duration=duration)


def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    gui = _pyautogui()
    clicks = 2 if double else 1
    gui.click(x=x, y=y, clicks=clicks, button=button)


def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> None:
    """Drag & drop: press at (x1, y1), release at (x2, y2)."""
    gui = _pyautogui()
    gui.moveTo(x1, y1, duration=0.2)
    gui.dragTo(x2, y2, duration=max(0.2, duration), button="left")


def scroll(amount: int, x: int | None = None, y: int | None = None) -> None:
    """Scroll by ``amount`` notches (positive = up) at an optional position."""
    gui = _pyautogui()
    if x is not None and y is not None:
        gui.moveTo(x, y, duration=0.1)
    gui.scroll(amount)
