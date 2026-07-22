"""Tests for the desktop tools: the Computer Engine's AI-facing contract.

The AI surface is deliberately narrow — a skill verb (``computer_run``), a set
of description-driven semantic UI actions (``ui_*``), and read-only observation
(``computer_state``/``computer_see``/``desktop_*``). No coordinate, keystroke,
or selector argument is ever exposed. These tests inject a fake engine through
``seedcode.tools.desktop`` so no real desktop action runs, and exercise the
gating, permission, and routing logic on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from seedcode.computer.permissions import DesktopGrant, DesktopSession
from seedcode.tools import TOOL_REGISTRY, PermissionManager, get_tool, tool_manifest
from seedcode.tools import desktop as desktop_tools
from seedcode.tools.permissions import PermissionLevel

# The full AI-facing desktop surface after the vNext rewrite.
DESKTOP_TOOL_NAMES = {
    "computer_run",
    "computer_state",
    "computer_see",
    "desktop_screenshot",
    "desktop_windows",
    "desktop_screen_info",
    "ui_click",
    "ui_double_click",
    "ui_right_click",
    "ui_type",
    "ui_wait_for",
    "ui_assert",
}

# Tool names removed from the AI surface — capabilities moved inside skills.
REMOVED_TOOL_NAMES = {
    "desktop_mouse",
    "desktop_type",
    "desktop_focus",
    "desktop_app",
    "desktop_registry",
    "desktop_see",
    "desktop_wait",
}


@dataclass
class _FakeResult:
    ok: bool = True
    detail: str = "did the thing"

    def for_model(self) -> str:
        return self.detail


@dataclass
class _FakeState:
    def describe(self) -> str:
        return "focused: Notepad"


@dataclass
class _FakeEngine:
    """Records every dispatched skill; answers observation calls with canned text."""

    calls: list[tuple[str, dict, dict | None]] = field(default_factory=list)
    controller: Any = None

    def run_skill(self, name, params=None, expected=None) -> _FakeResult:
        self.calls.append((name, dict(params or {}), expected))
        return _FakeResult(True, f"{name} ok")

    def state(self) -> _FakeState:
        return _FakeState()

    def see(self, window=None) -> str:
        return f"snapshot of {window or 'active window'}"


class GrantingSession(DesktopSession):
    """DesktopSession that records checks and grants everything (Once)."""

    def __init__(self):
        super().__init__(enabled=True, confirm=lambda c, d: DesktopGrant.ONCE)
        self.checked: list[str] = []

    def check(self, category, description):
        self.checked.append(category)
        super().check(category, description)


@pytest.fixture()
def engine(monkeypatch):
    """Inject a fake engine and force desktop availability."""
    fake = _FakeEngine()
    import seedcode.computer as computer

    # ``desktop.py`` imports get_engine/is_available from seedcode.computer
    # inside ``_engine()``; patch them at that source.
    monkeypatch.setattr(computer, "is_available", lambda: (True, "ok"))
    monkeypatch.setattr(computer, "get_engine", lambda perm, controller=None: fake)
    monkeypatch.setattr(desktop_tools, "get_controller", lambda: None)
    if hasattr(desktop_tools, "_queue_screenshot"):
        monkeypatch.setattr(desktop_tools, "_queue_screenshot", lambda *a, **k: None)
    return fake


@pytest.fixture()
def perm(tmp_path):
    """A Desktop-level manager with an all-granting session."""
    manager = PermissionManager(workspace=tmp_path, level=PermissionLevel.DESKTOP)
    manager.desktop = GrantingSession()
    return manager


def run(perm, tool_name, **args):
    return get_tool(tool_name).run(perm, args)


# --- registration & manifest --------------------------------------------------
class TestRegistration:
    def test_all_desktop_tools_registered(self):
        assert DESKTOP_TOOL_NAMES <= set(TOOL_REGISTRY)
        for name in DESKTOP_TOOL_NAMES:
            assert TOOL_REGISTRY[name].group == "desktop"

    def test_removed_tools_are_gone(self):
        assert REMOVED_TOOL_NAMES.isdisjoint(TOOL_REGISTRY)

    def test_no_coordinate_arguments_exposed(self):
        """The AI must never be offered a coordinate/keystroke/selector arg."""
        forbidden = {"x", "y", "to_x", "to_y", "coordinate", "coords", "keys", "selector"}
        for name, tool in TOOL_REGISTRY.items():
            if tool.group != "desktop":
                continue
            assert forbidden.isdisjoint(tool.args), f"{name} exposes a low-level arg"
            for desc in tool.args.values():
                assert "coordinate" not in desc.lower(), f"{name} mentions coordinates"

    def test_core_manifest_excludes_desktop(self):
        manifest = tool_manifest()
        assert "read_file" in manifest and "computer_run" not in manifest

    def test_full_manifest_includes_desktop(self):
        manifest = tool_manifest(("core", "desktop"))
        assert "read_file" in manifest and "computer_run" in manifest


# --- gating ------------------------------------------------------------------
class TestGating:
    def test_level_below_desktop_blocks(self, engine, tmp_path):
        from seedcode.tools.base import ToolError

        low = PermissionManager(workspace=tmp_path, level=PermissionLevel.WORKSPACE)
        low.desktop = GrantingSession()
        with pytest.raises(ToolError, match="Desktop permission"):
            run(low, "computer_state")

    def test_no_session_blocks(self, engine, perm):
        from seedcode.tools.base import ToolError

        perm.desktop = None
        with pytest.raises(ToolError, match="/assist on"):
            run(perm, "computer_state")

    def test_disabled_session_blocks(self, engine, perm):
        from seedcode.tools.base import ToolError

        perm.desktop.enabled = False
        with pytest.raises(ToolError, match="/assist on"):
            run(perm, "computer_state")

    def test_unavailable_engine_blocks(self, engine, perm, monkeypatch):
        import seedcode.computer as computer
        from seedcode.tools.base import ToolError

        monkeypatch.setattr(computer, "is_available", lambda: (False, "missing deps"))
        with pytest.raises(ToolError, match="missing deps"):
            run(perm, "computer_state")

    def test_denied_grant_becomes_permission_error(self, engine, perm):
        from seedcode.tools.permissions import PermissionError_

        perm.desktop.confirm = lambda c, d: DesktopGrant.DENY
        with pytest.raises(PermissionError_):
            run(perm, "ui_click", target="the OK button")


# --- routing ------------------------------------------------------------------
class TestRouting:
    def test_computer_run_dispatches_skill(self, engine, perm):
        result = run(perm, "computer_run", skill="launch_app", params={"target": "notepad"})
        assert result.ok
        assert engine.calls == [("launch_app", {"target": "notepad"}, None)]

    def test_computer_run_requires_skill(self, engine, perm):
        from seedcode.tools.base import ToolError

        with pytest.raises(ToolError, match="skill"):
            run(perm, "computer_run")

    def test_computer_run_rejects_non_object_params(self, engine, perm):
        result = run(perm, "computer_run", skill="launch_app", params="notepad")
        assert not result.ok and "object" in result.output

    def test_computer_run_passes_expected(self, engine, perm):
        run(perm, "computer_run", skill="launch_app",
            params={"target": "notepad"}, expected={"window": "Notepad"})
        assert engine.calls[0][2] == {"window": "Notepad"}

    def test_ui_click_routes_with_target(self, engine, perm):
        assert run(perm, "ui_click", target="the Save button").ok
        assert engine.calls == [("ui_click", {"target": "the Save button"}, None)]

    def test_ui_actions_require_target(self, engine, perm):
        for verb in ("ui_click", "ui_double_click", "ui_right_click",
                     "ui_wait_for", "ui_assert"):
            result = run(perm, verb, target="")
            assert not result.ok and "target" in result.output

    def test_ui_type_carries_text_and_secret(self, engine, perm):
        assert run(perm, "ui_type", target="the password box",
                   text="hunter2", secret="true").ok
        name, params, _ = engine.calls[0]
        assert name == "ui_type"
        assert params == {"target": "the password box", "text": "hunter2", "secret": True}

    def test_ui_type_requires_text(self, engine, perm):
        from seedcode.tools.base import ToolError

        with pytest.raises(ToolError, match="text"):
            run(perm, "ui_type", target="the box")

    def test_observation_routes(self, engine, perm):
        assert "focused" in run(perm, "computer_state").output
        assert "snapshot" in run(perm, "computer_see", window="Notepad").output


# --- sensitive skills need Full System ---------------------------------------
class TestSensitiveSkills:
    def test_sensitive_skill_needs_full_system(self, engine, perm, monkeypatch):
        """A sensitive skill is refused at DESKTOP and confirmed at FULL_SYSTEM."""
        from seedcode.computer.skills import REGISTRY, Skill
        from seedcode.tools.permissions import PermissionError_

        sensitive = Skill(
            name="danger", summary="destructive test skill",
            level=PermissionLevel.FULL_SYSTEM,
            body=lambda ctx, params: None, params={}, sensitive=True,
        )
        monkeypatch.setattr(REGISTRY, "get", lambda n: sensitive if n == "danger" else None)

        # DESKTOP is not enough for a sensitive skill.
        with pytest.raises(PermissionError_):
            run(perm, "computer_run", skill="danger")

        # FULL_SYSTEM passes the level gate and reaches the engine.
        perm.level = PermissionLevel.FULL_SYSTEM
        assert run(perm, "computer_run", skill="danger").ok
        assert engine.calls == [("danger", {}, None)]


# --- agent loop integration ---------------------------------------------------
class TestAgentIntegration:
    def make_agent(self, tmp_path, desktop_session=None):
        from seedcode.core.agent import AgentEngine
        from seedcode.core.models import AppConfig

        config = AppConfig()
        config.model = "test-model"
        perm = PermissionManager(workspace=tmp_path, level=PermissionLevel.DESKTOP)
        perm.desktop = desktop_session
        return AgentEngine(config, perm)

    def test_prompt_without_desktop_omits_tools(self, tmp_path):
        agent = self.make_agent(tmp_path)
        prompt = agent.messages[0].content
        assert "computer_run" not in prompt and "COMPUTER ENGINE" not in prompt.upper()

    def test_prompt_with_desktop_lists_catalog(self, tmp_path, monkeypatch):
        import seedcode.core.agent as agent_mod

        monkeypatch.setattr(agent_mod.AgentEngine, "_desktop_active", lambda self: True)
        # Pin the text protocol so the catalog travels as prompt text.
        monkeypatch.setattr(agent_mod.AgentEngine, "_native_active", lambda self: False)
        agent = self.make_agent(tmp_path, DesktopSession(enabled=True))
        agent.refresh_system_prompt()
        prompt = agent.messages[0].content
        # The catalog and the AI-as-planner contract are present; no coordinates.
        assert "computer_run" in prompt
        assert "launch_app" in prompt
        assert "desktop_mouse" not in prompt

    def test_drain_images_empty_without_session(self, tmp_path):
        agent = self.make_agent(tmp_path)
        assert agent._drain_images() == []

    def test_drain_images_clears_queue(self, tmp_path):
        session = DesktopSession(enabled=True)
        session.pending_images.append("base64data")
        agent = self.make_agent(tmp_path, session)
        agent._drain_images()  # provider lookup may fail -> [] — but queue drains
        assert session.pending_images == []
