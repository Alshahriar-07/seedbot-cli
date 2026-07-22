"""Keyboard driver: text typing and hotkeys via pyautogui.

Typing uses a small per-key interval so target applications reliably receive
every keystroke; hotkeys accept the pyautogui key-name vocabulary
("ctrl", "alt", "shift", "win", "enter", "f5", single characters, ...).
"""

from __future__ import annotations

# Bound one type_text call: pathological lengths point at a confused model.
MAX_TEXT_LENGTH = 5_000

# Keys allowed in hotkey combos (a safety vocabulary, not an exhaustive list
# of what pyautogui supports — unknown names are rejected loudly).
_MODIFIERS = {"ctrl", "alt", "shift", "win", "cmd", "fn"}
_NAMED_KEYS = {
    "enter", "return", "tab", "space", "backspace", "delete", "del", "esc",
    "escape", "home", "end", "pageup", "pagedown", "up", "down", "left",
    "right", "insert", "printscreen", "capslock", "numlock",
} | {f"f{i}" for i in range(1, 25)}


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    return pyautogui


def validate_keys(keys: list[str]) -> list[str]:
    """Normalise and validate hotkey names; raises ValueError on junk."""
    cleaned = []
    for key in keys:
        name = str(key).strip().lower()
        if not name:
            continue
        if name in _MODIFIERS or name in _NAMED_KEYS or len(name) == 1:
            cleaned.append(name)
        else:
            raise ValueError(f"Unknown key '{key}' in hotkey combination.")
    if not cleaned:
        raise ValueError("Hotkey combination is empty.")
    return cleaned


def type_text(text: str, interval: float = 0.02) -> None:
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"Text is too long to type ({len(text)} chars; max {MAX_TEXT_LENGTH})."
        )
    _pyautogui().typewrite(text, interval=interval)


def hotkey(keys: list[str]) -> None:
    _pyautogui().hotkey(*validate_keys(keys))
