"""Tests for the Computer Engine: controller, permissions, availability gate.

Everything runs against fake drivers — no real mouse, windows, or registry
are touched, so the suite is safe on CI and on developer machines alike.
"""

from __future__ import annotations

import pytest

from seedcode.computer import is_available
from seedcode.computer.controller import ComputerController, ComputerError, MAX_WAIT_S
from seedcode.computer.permissions import (
    CATEGORY_APPS,
    CATEGORY_CONTROL,
    CATEGORY_REGISTRY_WRITE,
    CATEGORY_SECRET,
    DesktopGrant,
    DesktopSession,
)
from seedcode.computer.screen import MonitorInfo, ScreenGeometry
from seedcode.computer.windows import WindowInfo
from seedcode.tools.permissions import PermissionError_


# --- fakes -------------------------------------------------------------------
class FakeScreen:
    def __init__(self, width=1920, height=1080, left=0, top=0):
        self._geo = ScreenGeometry(
            left=left,
            top=top,
            width=width,
            height=height,
            monitors=[MonitorInfo(1, left, top, width, height, True)],
        )
        self.captures = []

    def geometry(self):
        return self._geo

    def capture(self, region=None, monitor=None, save_to=None):
        self.captures.append((region, monitor))
        return save_to or "C:/fake/shot.png"


class FakeMouse:
    def __init__(self):
        self.actions = []

    def move(self, x, y, duration=0.2):
        self.actions.append(("move", x, y))

    def click(self, x, y, button="left", double=False):
        self.actions.append(("click", x, y, button, double))

    def drag(self, x1, y1, x2, y2, duration=0.5):
        self.actions.append(("drag", x1, y1, x2, y2))

    def scroll(self, amount, x=None, y=None):
        self.actions.append(("scroll", amount, x, y))


class FakeKeyboard:
    def __init__(self):
        self.actions = []

    def type_text(self, text, interval=0.02):
        self.actions.append(("type", text))

    def hotkey(self, keys):
        self.actions.append(("hotkey", tuple(keys)))


class FakeWindows:
    def __init__(self):
        self.windows = [
            WindowInfo("Notepad — hello.txt", 0, 0, 800, 600, True, False),
            WindowInfo("Browser", 100, 100, 1200, 800, False, False),
        ]
        self.actions = []

    def list_windows(self):
        return self.windows

    def active_window(self):
        return next((w for w in self.windows if w.active), None)

    def focus_window(self, title):
        self.actions.append(("focus", title))
        for w in self.windows:
            w.active = title.lower() in w.title.lower()
        return self.active_window()

    def open_app(self, target):
        self.actions.append(("open", target))
        return f"Launched '{target}'."

    def close_window(self, title, force=False):
        self.actions.append(("close", title, force))
        return f"Closed '{title}'."


class FakeVision:
    def snapshot(self, window_title=None):
        return ("Notepad", [])

    def describe_snapshot(self, title, elements):
        return f'Window "{title}" — 0 elements'

    def element_at(self, x, y):
        return 'button "OK"'

    def ocr_screenshot(self, path):
        return "fake ocr text"


class FakeRegistry:
    def __init__(self):
        self.written = []

    def read_value(self, path, name):
        return f"{path} : {name} = 'value'"

    def list_key(self, path):
        return f"{path}: (empty)"

    def write_value(self, path, name, value, value_type="REG_SZ"):
        self.written.append((path, name, value, value_type))
        return f"Wrote {path} : {name}"

    def delete_value(self, path, name):
        self.written.append(("delete", path, name))
        return f"Deleted {path} : {name}"


@pytest.fixture()
def controller(monkeypatch):
    # Verification pauses are pointless against fakes — make them instant.
    import seedcode.computer.controller as controller_mod

    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)
    return ComputerController(
        mouse=FakeMouse(),
        keyboard=FakeKeyboard(),
        screen=FakeScreen(),
        windows=FakeWindows(),
        vision=FakeVision(),
        registry=FakeRegistry(),
    )


# --- availability ------------------------------------------------------------
class TestAvailability:
    def test_is_available_returns_tuple(self):
        ok, reason = is_available()
        assert isinstance(ok, bool) and isinstance(reason, str) and reason


# --- coordinate safety -------------------------------------------------------
class TestCoordinates:
    def test_valid_point_passes(self, controller):
        assert controller.validate_point(10, 20) == (10, 20)

    def test_out_of_bounds_is_blocked(self, controller):
        with pytest.raises(ComputerError, match="outside the desktop"):
            controller.validate_point(5000, 5000)
        with pytest.raises(ComputerError):
            controller.validate_point(-10, 50)

    def test_non_numeric_is_blocked(self, controller):
        with pytest.raises(ComputerError, match="integers"):
            controller.validate_point("abc", 5)

    def test_click_never_fires_when_out_of_bounds(self, controller):
        with pytest.raises(ComputerError):
            controller.mouse_click(99999, 5)
        assert controller.mouse.actions == []  # the blind click never happened


# --- actions carry verification ---------------------------------------------
class TestVerification:
    def test_click_reports_post_state(self, controller):
        out = controller.mouse_click(100, 200)
        assert "[verify]" in out and "active window" in out and 'button "OK"' in out
        assert ("click", 100, 200, "left", False) in controller.mouse.actions

    def test_type_reports_post_state(self, controller):
        out = controller.type_text("hello")
        assert "[verify]" in out
        assert ("type", "hello") in controller.keyboard.actions

    def test_drag_and_scroll(self, controller):
        assert "Dragged" in controller.mouse_drag(10, 10, 200, 200)
        out = controller.mouse_scroll(100)  # clamped to 50
        assert "Scrolled 50" in out

    def test_focus_verifies_and_succeeds(self, controller):
        out = controller.focus_window("Browser")
        assert "Focused" in out and "Browser" in out

    def test_focus_that_never_sticks_raises(self, controller):
        class StubbornWindows(FakeWindows):
            def focus_window(self, title):
                return self.active_window()  # focus silently does nothing

        controller.windows = StubbornWindows()
        with pytest.raises(ComputerError, match="did not stick"):
            controller.focus_window("Browser")

    def test_wait_is_clamped(self, controller):
        assert f"Waited {MAX_WAIT_S:g}s" in controller.wait(9999)


# --- keyboard validation -----------------------------------------------------
class TestKeyboard:
    def test_unknown_hotkey_is_rejected(self, controller):
        class StrictKeyboard(FakeKeyboard):
            def hotkey(self, keys):
                from seedcode.computer.keyboard import validate_keys

                validate_keys(keys)
                super().hotkey(keys)

        controller.keyboard = StrictKeyboard()
        with pytest.raises(ComputerError, match="Unknown key"):
            controller.hotkey(["ctrl", "notakey"])
        assert "Pressed ctrl+s" in controller.hotkey(["ctrl", "s"])

    def test_validate_keys_directly(self):
        from seedcode.computer.keyboard import validate_keys

        assert validate_keys(["Ctrl", "S"]) == ["ctrl", "s"]
        with pytest.raises(ValueError):
            validate_keys([])


# --- desktop session (Y/A/N grants) ------------------------------------------
class TestDesktopSession:
    def make(self, answers: list[DesktopGrant], enabled=True):
        asked = []

        def confirm(category, description):
            asked.append((category, description))
            return answers.pop(0)

        return DesktopSession(enabled=enabled, confirm=confirm), asked

    def test_disabled_blocks_everything(self):
        session, asked = self.make([], enabled=False)
        with pytest.raises(PermissionError_, match="desktop mode is off"):
            session.check(CATEGORY_CONTROL, "click")
        assert asked == []  # never even asked

    def test_once_asks_every_time(self):
        session, asked = self.make([DesktopGrant.ONCE, DesktopGrant.ONCE])
        session.check(CATEGORY_CONTROL, "click 1")
        session.check(CATEGORY_CONTROL, "click 2")
        assert len(asked) == 2

    def test_always_is_remembered_for_category(self):
        session, asked = self.make([DesktopGrant.ALWAYS])
        session.check(CATEGORY_CONTROL, "click 1")
        session.check(CATEGORY_CONTROL, "click 2")  # no new ask
        assert len(asked) == 1

    def test_deny_is_remembered_and_blocks(self):
        session, asked = self.make([DesktopGrant.DENY])
        with pytest.raises(PermissionError_):
            session.check(CATEGORY_APPS, "open app")
        with pytest.raises(PermissionError_):
            session.check(CATEGORY_APPS, "open app again")  # still denied, no re-ask
        assert len(asked) == 1

    def test_grants_are_per_category(self):
        session, asked = self.make([DesktopGrant.ALWAYS, DesktopGrant.ONCE])
        session.check(CATEGORY_CONTROL, "click")
        session.check(CATEGORY_APPS, "open")  # different category -> new ask
        assert len(asked) == 2

    def test_sensitive_never_remembers_always(self):
        session, asked = self.make(
            [DesktopGrant.ALWAYS, DesktopGrant.ALWAYS, DesktopGrant.ALWAYS]
        )
        session.check(CATEGORY_REGISTRY_WRITE, "write 1")
        session.check(CATEGORY_REGISTRY_WRITE, "write 2")
        session.check(CATEGORY_SECRET, "type password")
        assert len(asked) == 3  # every sensitive action asked individually
        assert session.grants == {}  # and nothing was stored

    def test_sensitive_deny_blocks_that_action(self):
        session, _ = self.make([DesktopGrant.DENY])
        with pytest.raises(PermissionError_, match="denied"):
            session.check(CATEGORY_REGISTRY_WRITE, "write HKLM")

    def test_reset_clears_grants(self):
        session, asked = self.make([DesktopGrant.ALWAYS, DesktopGrant.ONCE])
        session.check(CATEGORY_CONTROL, "click")
        session.reset()
        session.check(CATEGORY_CONTROL, "click")  # asks again after reset
        assert len(asked) == 2

    def test_default_callback_denies(self):
        session = DesktopSession(enabled=True)
        with pytest.raises(PermissionError_):
            session.check(CATEGORY_CONTROL, "click")


# --- registry ---------------------------------------------------------------
class TestRegistry:
    def test_parse_key_aliases(self):
        import sys

        if sys.platform != "win32":
            pytest.skip("winreg is Windows-only")
        from seedcode.computer.registry import parse_key

        _, subkey, display = parse_key(r"HKCU\Software\SeedCode")
        assert subkey == r"Software\SeedCode"
        assert display == r"HKEY_CURRENT_USER\Software\SeedCode"
        with pytest.raises(ValueError, match="hive"):
            parse_key(r"NOPE\Software")

    def test_controller_registry_roundtrip(self, controller):
        assert "value" in controller.registry_read("HKCU\\X", "name")
        assert "empty" in controller.registry_list("HKCU\\X")
        controller.registry_write("HKCU\\X", "n", "v", "REG_SZ")
        assert controller.registry.written == [("HKCU\\X", "n", "v", "REG_SZ")]
