"""Tests for the skill engine and built-in catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedcode.computer import catalog  # noqa: F401 — populates REGISTRY
from seedcode.computer.skills import (
    Outcome,
    REGISTRY,
    Skill,
    SkillContext,
    SkillError,
    SkillRegistry,
)
from seedcode.tools.permissions import PermissionLevel, PermissionManager


class _FakeController:
    def __init__(self):
        self.calls = []
        self._windows = []

    def list_windows(self):
        return list(self._windows)

    def focus_window(self, title):
        self.calls.append(("focus", title))
        return type("W", (), {"title": title})()

    def open_app(self, target):
        self.calls.append(("open", target))

    def close_app(self, target, force=False):
        self.calls.append(("close", target))

    def browser_navigate(self, url):
        self.calls.append(("nav", url))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def type_text(self, text):
        self.calls.append(("type", text))

    def mouse_click(self, x, y, button="left", double=False):
        self.calls.append(("click", x, y))


class _FakeState:
    def __init__(self):
        self.actions = []
        self.focus = None

    def record_action(self, d):
        self.actions.append(d)

    def note_focus(self, t):
        self.focus = t


def _ctx(level=PermissionLevel.DESKTOP, workspace=None):
    perms = PermissionManager(workspace=workspace or Path.cwd(), level=level)
    return SkillContext(
        controller=_FakeController(),
        resolver=None,
        state=_FakeState(),
        permissions=perms,
    )


# --- engine -----------------------------------------------------------------

def test_registry_lookup_case_insensitive():
    assert REGISTRY.get("LAUNCH_APP") is not None
    assert REGISTRY.get("launch_app") is REGISTRY.get("LAUNCH_APP")


def test_skill_enforces_permission_floor():
    ctx = _ctx(level=PermissionLevel.WORKSPACE)  # below DESKTOP
    launch = REGISTRY.get("launch_app")
    from seedcode.tools.permissions import PermissionError_

    with pytest.raises(PermissionError_):
        launch.run(ctx, {"target": "notepad"})


def test_manifest_hides_skills_above_level():
    ro = REGISTRY.manifest(max_level=PermissionLevel.READ_ONLY)
    assert "launch_app" not in ro  # DESKTOP skill hidden at read-only
    desktop = REGISTRY.manifest(max_level=PermissionLevel.DESKTOP)
    assert "launch_app" in desktop


def test_custom_registry_isolated():
    reg = SkillRegistry()
    reg.register(Skill("noop", "does nothing", PermissionLevel.READ_ONLY,
                       lambda c, p: Outcome("ok")))
    assert reg.get("noop") is not None
    assert reg.get("launch_app") is None  # separate from the global REGISTRY


# --- catalog behaviour ------------------------------------------------------

def test_launch_app_focuses_existing_window():
    ctx = _ctx()
    ctx.controller._windows = [type("W", (), {"title": "Untitled - Notepad"})()]
    out = REGISTRY.get("launch_app").run(ctx, {"target": "notepad"})
    assert ("focus", "Untitled - Notepad") in ctx.controller.calls
    assert ("open", "notepad") not in ctx.controller.calls
    assert out.expected == {"window": "notepad"}


def test_launch_app_opens_when_absent():
    ctx = _ctx()
    REGISTRY.get("launch_app").run(ctx, {"target": "notepad"})
    assert ("open", "notepad") in ctx.controller.calls


def test_youtube_search_builds_url():
    ctx = _ctx()
    out = REGISTRY.get("youtube_search").run(ctx, {"query": "lofi beats"})
    nav = [c for c in ctx.controller.calls if c[0] == "nav"][0]
    assert "youtube.com/results" in nav[1]
    assert "lofi" in nav[1]
    assert out.expected == {"browser_url": "youtube.com"}


def test_missing_required_param_raises():
    ctx = _ctx()
    with pytest.raises(SkillError):
        REGISTRY.get("google_search").run(ctx, {})


def test_create_python_project_writes_files(tmp_path):
    ctx = _ctx(level=PermissionLevel.WORKSPACE, workspace=tmp_path)
    out = REGISTRY.get("create_python_project").run(ctx, {"name": "demo"})
    main = tmp_path / "demo" / "src" / "main.py"
    assert main.is_file()
    assert "Hello from demo" in main.read_text()
    assert out.expected == {"file_exists": str(main)}


def test_save_current_file_sends_ctrl_s():
    ctx = _ctx()
    REGISTRY.get("save_current_file").run(ctx, {})
    assert ("hotkey", ("ctrl", "s")) in ctx.controller.calls
