"""Tests for the skill dispatcher and ComputerEngine facade."""

from __future__ import annotations

from pathlib import Path

from seedcode.computer import catalog  # noqa: F401 — populate REGISTRY
from seedcode.computer.dispatcher import DispatchResult, SkillDispatcher
from seedcode.computer.engine import ComputerEngine
from seedcode.computer.recovery import RecoveryEngine
from seedcode.computer.resolver import ElementResolver
from seedcode.computer.skills import REGISTRY
from seedcode.computer.state import StateManager
from seedcode.computer.verifier import VerificationEngine
from seedcode.tools.permissions import PermissionLevel, PermissionManager

import pytest


@pytest.fixture(autouse=True)
def _isolated_app_dir(tmp_path, monkeypatch):
    """Keep execution-log persistence out of the real ~/.seedcode."""
    import seedcode.utils.helpers as helpers

    monkeypatch.setattr(helpers, "app_dir", lambda: tmp_path)
    return tmp_path


class _Win:
    def __init__(self, title):
        self.title = title

    def describe(self):
        return self.title


class _FakeWindowsDriver:
    def __init__(self):
        self.titles = []

    def list_windows(self):
        return [_Win(t) for t in self.titles]

    def active_window(self):
        return _Win(self.titles[-1]) if self.titles else None


class _El:
    def __init__(self, role, name, x, y):
        self.role, self.name, self.x, self.y = role, name, x, y
        self.enabled = True

    def describe(self):
        return f"{self.role} '{self.name}'"


class _FakeVisionDriver:
    def __init__(self):
        self.elements = []

    def snapshot(self, window_title=None):
        return ("W", list(self.elements))

    def ocr_available(self):
        return False


class _FakeController:
    """A controller whose open_app actually 'creates' a window, so verify passes."""

    def __init__(self):
        self.windows = _FakeWindowsDriver()
        self.vision = _FakeVisionDriver()
        self.mouse = None
        self.calls = []

    def list_windows(self):
        return self.windows.list_windows()

    def focus_window(self, title):
        self.calls.append(("focus", title))
        return _Win(title)

    def open_app(self, target):
        self.calls.append(("open", target))
        self.windows.titles.append(target)  # window now "exists"

    def close_app(self, target, force=False):
        self.calls.append(("close", target))
        self.windows.titles = [t for t in self.windows.titles if target.lower() not in t.lower()]

    def browser_navigate(self, url):
        self.calls.append(("nav", url))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def type_text(self, text):
        self.calls.append(("type", text))

    def mouse_click(self, x, y, button="left", double=False):
        self.calls.append(("click", x, y))

    def wait(self, s):
        self.calls.append(("wait", s))

    def see(self, title=None):
        return "snapshot"


def _dispatcher(controller, level=PermissionLevel.DESKTOP, workspace=None):
    perms = PermissionManager(workspace=workspace or Path.cwd(), level=level)
    fast_verifier = VerificationEngine(
        vision=controller.vision, windows=controller.windows, timeout_s=0.0, poll_s=0.0
    )
    return SkillDispatcher(
        controller=controller,
        resolver=ElementResolver(vision=controller.vision, screen=None),
        state=StateManager(windows=controller.windows, mouse=None),
        permissions=perms,
        registry=REGISTRY,
        verifier=fast_verifier,
        recovery=RecoveryEngine(controller=controller),
    )


# --- dispatch happy path ----------------------------------------------------

def test_dispatch_launch_app_verifies():
    ctrl = _FakeController()
    result = _dispatcher(ctrl).dispatch("launch_app", {"target": "Notepad"})
    assert result.ok
    assert ("open", "Notepad") in ctrl.calls
    assert result.log.succeeded
    assert "verify" in result.log.render().lower()


def test_dispatch_unknown_skill_reports():
    result = _dispatcher(_FakeController()).dispatch("frobnicate", {})
    assert not result.ok
    assert result.replan_hint
    assert "No such skill" in result.detail


def test_dispatch_semantic_click_resolves_description():
    ctrl = _FakeController()
    ctrl.vision.elements = [_El("button", "Submit", 120, 60)]
    result = _dispatcher(ctrl).dispatch("ui_click", {"target": "Submit button"})
    assert result.ok
    assert ("click", 120, 60) in ctrl.calls


def test_dispatch_missing_permission_is_failure_not_crash():
    ctrl = _FakeController()
    result = _dispatcher(ctrl, level=PermissionLevel.WORKSPACE).dispatch(
        "launch_app", {"target": "Notepad"}
    )
    assert not result.ok
    assert result.replan_hint


def test_dispatch_verify_failure_triggers_recovery():
    # open_app that never creates a window -> verify always fails -> recovery runs.
    ctrl = _FakeController()
    ctrl.open_app = lambda target: ctrl.calls.append(("open", target))  # no window
    result = _dispatcher(ctrl).dispatch("launch_app", {"target": "Ghost"})
    assert not result.ok
    trail = result.log.render().lower()
    assert "recover" in trail


# --- engine facade ----------------------------------------------------------

def test_engine_run_skill_and_state():
    ctrl = _FakeController()
    perms = PermissionManager(level=PermissionLevel.DESKTOP)
    engine = ComputerEngine(permissions=perms, controller=ctrl)
    # Patch the dispatcher's verifier to be instant.
    engine._verifier._timeout_s = 0.0
    engine._verifier._poll_s = 0.0
    engine._dispatcher._verifier = engine._verifier
    result = engine.run_skill("launch_app", {"target": "Notepad"})
    assert isinstance(result, DispatchResult)
    assert result.ok
    assert "launch_app" in engine.catalog()


def test_engine_catalog_respects_level():
    ctrl = _FakeController()
    perms = PermissionManager(level=PermissionLevel.READ_ONLY)
    engine = ComputerEngine(permissions=perms, controller=ctrl)
    assert "launch_app" not in engine.catalog()  # DESKTOP skill hidden


def test_dispatch_persists_execution_log(tmp_path):
    """Every dispatched action appends one JSON line to the day's log file."""
    import json

    ctrl = _FakeController()
    _dispatcher(ctrl).dispatch("launch_app", {"target": "Notepad"})
    logs = list((tmp_path / "logs").glob("execution-*.jsonl"))
    assert len(logs) == 1
    record = json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["ok"] is True
    assert record["label"] == "launch_app"
    stages = [s["stage"] for s in record["stages"]]
    assert stages[0] == "plan" and "verify" in stages and stages[-1] == "done"
