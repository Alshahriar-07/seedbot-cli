"""Tests for the element resolver and Computer Engine state manager."""

from __future__ import annotations

import pytest

from seedcode.computer.resolver import ElementResolver, ResolveError
from seedcode.computer.state import ComputerState, StateManager, _app_from_title


class _El:
    """Stand-in for vision.UIElement."""

    def __init__(self, role, name, x, y, enabled=True):
        self.role = role
        self.name = name
        self.x = x
        self.y = y
        self.width = 40
        self.height = 20
        self.enabled = enabled


class _FakeVision:
    def __init__(self, elements):
        self._elements = elements

    def snapshot(self, window_title=None):
        return ("Test Window", self._elements)

    def ocr_available(self):
        return False


class _FakeWindow:
    def __init__(self, title):
        self.title = title

    def describe(self):
        return self.title


class _FakeWindows:
    def __init__(self, title):
        self._title = title

    def active_window(self):
        return _FakeWindow(self._title) if self._title else None


class _FakeMouse:
    def __init__(self, pos):
        self._pos = pos

    def position(self):
        return self._pos


# --- resolver ---------------------------------------------------------------

def test_resolve_by_name_and_role():
    vision = _FakeVision([
        _El("button", "Sign in", 100, 50),
        _El("button", "Cancel", 200, 50),
        _El("input", "Search", 300, 80),
    ])
    r = ElementResolver(vision=vision, screen=None)
    hit = r.resolve("Sign in button")
    assert hit.role == "button"
    assert hit.name == "Sign in"
    assert (hit.x, hit.y) == (100, 50)
    assert hit.source == "accessibility"


def test_resolve_prefers_matching_role():
    # "search" as both a button label and an input; asking for the box wins the input.
    vision = _FakeVision([
        _El("button", "Search", 10, 10),
        _El("input", "Search", 20, 20),
    ])
    r = ElementResolver(vision=vision, screen=None)
    hit = r.resolve("Search box")
    assert hit.role == "input"
    assert (hit.x, hit.y) == (20, 20)


def test_resolve_unknown_raises():
    vision = _FakeVision([_El("button", "OK", 5, 5)])
    r = ElementResolver(vision=vision, screen=None)
    with pytest.raises(ResolveError):
        r.resolve("Nonexistent widget")


def test_resolve_empty_description_raises():
    r = ElementResolver(vision=_FakeVision([]), screen=None)
    with pytest.raises(ResolveError):
        r.resolve("   ")


def test_resolve_never_returns_below_threshold():
    # A weak, unrelated match must fail rather than click the wrong element.
    vision = _FakeVision([_El("button", "Preferences", 1, 1)])
    r = ElementResolver(vision=vision, screen=None)
    with pytest.raises(ResolveError):
        r.resolve("zzzzz")


# --- state manager ----------------------------------------------------------

def test_app_from_title_splits_on_dash():
    assert _app_from_title("report.txt - Notepad") == "Notepad"
    assert _app_from_title("Inbox — Outlook") == "Outlook"
    assert _app_from_title("Just A Title") == "Just A Title"
    assert _app_from_title(None) is None


def test_state_refresh_reads_drivers():
    sm = StateManager(windows=_FakeWindows("doc.py - VS Code"), mouse=_FakeMouse((640, 480)))
    state = sm.refresh()
    assert state.focused_window == "doc.py - VS Code"
    assert state.focused_app == "VS Code"
    assert state.pointer == (640, 480)


def test_state_refresh_survives_driver_errors():
    class _Boom:
        def active_window(self):
            raise RuntimeError("no desktop")

        def position(self):
            raise RuntimeError("no mouse")

    sm = StateManager(windows=_Boom(), mouse=_Boom())
    state = sm.refresh()  # must not raise
    assert isinstance(state, ComputerState)


def test_action_trail_is_bounded():
    sm = StateManager(windows=_FakeWindows(None), mouse=_FakeMouse(None))
    for i in range(50):
        sm.record_action(f"action {i}")
    assert len(sm.state.recent_actions) <= 12
    assert sm.state.recent_actions[-1] == "action 49"


def test_clipboard_preview_truncates():
    sm = StateManager(windows=_FakeWindows(None), mouse=_FakeMouse(None))
    sm.set_clipboard("x" * 200)
    assert sm.state.clipboard_preview.endswith("…")
    assert len(sm.state.clipboard_preview) <= 61


def test_state_describe_is_readable():
    sm = StateManager(windows=_FakeWindows("a - App"), mouse=_FakeMouse((1, 2)))
    sm.refresh()
    sm.record_action("clicked Sign in")
    text = sm.state.describe()
    assert "App" in text
    assert "clicked Sign in" in text
