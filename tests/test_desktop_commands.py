"""Tests for the desktop commands: /desktop, /computer, /screenshot, /windows."""

from __future__ import annotations

import pytest

from seedcode.commands import CommandContext, dispatch
from seedcode.core.models import AppConfig


class StubUI:
    """Records every UI call so tests can assert on what the user saw."""

    def __init__(self):
        self.messages = []  # (kind, text)

    def _record(self, kind):
        def method(text="", *args, **kwargs):
            self.messages.append((kind, str(text)))

        return method

    def __getattr__(self, name):
        return self._record(name)

    def texts(self, kind=None):
        return [t for k, t in self.messages if kind is None or k == kind]


@pytest.fixture()
def ctx(monkeypatch):
    # Never write the real user's config from tests. /desktop routes into
    # Assist Mode, so the save happens there.
    monkeypatch.setattr("seedcode.commands.assist.save_config", lambda config: None)
    return CommandContext(ui=StubUI(), config=AppConfig(), engine=None)


def force_available(monkeypatch, ok=True, reason="ok"):
    # Both the desktop command and Assist Mode probe the engine.
    monkeypatch.setattr(
        "seedcode.commands.desktop.is_available", lambda: (ok, reason)
    )
    monkeypatch.setattr(
        "seedcode.commands.assist.is_available", lambda: (ok, reason)
    )


class TestDesktopToggle:
    """/desktop is a legacy alias that now routes into Assist Mode."""

    def test_on_enables_assist(self, ctx, monkeypatch):
        force_available(monkeypatch)
        dispatch(ctx, "/desktop on")
        # Assist Mode turns on; desktop capability follows engine availability.
        assert ctx.config.agent_mode is True
        assert ctx.config.desktop_mode is True
        assert any("Assist Mode ON" in t for t in ctx.ui.texts("success"))

    def test_on_without_engine_still_enables_assist(self, ctx, monkeypatch):
        force_available(monkeypatch, ok=False, reason="Missing packages: pyautogui")
        dispatch(ctx, "/desktop on")
        # AI/filesystem/terminal still work; only desktop capability is off.
        assert ctx.config.agent_mode is True
        assert ctx.config.desktop_mode is False

    def test_off(self, ctx, monkeypatch):
        force_available(monkeypatch)
        ctx.config.agent_mode = True
        ctx.config.desktop_mode = True
        dispatch(ctx, "/desktop off")
        assert ctx.config.agent_mode is False
        assert ctx.config.desktop_mode is False

    def test_bare_toggles(self, ctx, monkeypatch):
        force_available(monkeypatch)
        dispatch(ctx, "/desktop")
        assert ctx.config.agent_mode is True
        dispatch(ctx, "/desktop")
        assert ctx.config.agent_mode is False

    def test_bad_arg_warns(self, ctx, monkeypatch):
        force_available(monkeypatch)
        dispatch(ctx, "/desktop maybe")
        assert ctx.config.agent_mode is False
        assert any("Usage" in t for t in ctx.ui.texts("warning"))


class TestComputerStatus:
    def test_shows_panel(self, ctx, monkeypatch):
        force_available(monkeypatch, ok=False, reason="Windows-only")
        dispatch(ctx, "/computer")
        assert ctx.ui.texts("panel")  # a status panel was rendered


class TestScreenshotAndWindows:
    def test_screenshot_unavailable(self, ctx, monkeypatch):
        force_available(monkeypatch, ok=False, reason="Missing packages: mss")
        dispatch(ctx, "/screenshot")
        assert any("Missing packages" in t for t in ctx.ui.texts("error"))

    def test_windows_unavailable(self, ctx, monkeypatch):
        force_available(monkeypatch, ok=False, reason="Missing packages: pygetwindow")
        dispatch(ctx, "/windows")
        assert any("Missing packages" in t for t in ctx.ui.texts("error"))

    def test_screenshot_available(self, ctx, monkeypatch, tmp_path):
        force_available(monkeypatch)

        class FakeController:
            def screenshot(self, save_to=None):
                return str(save_to or tmp_path / "shot.png")

        monkeypatch.setattr(
            "seedcode.tools.desktop.get_controller", lambda: FakeController()
        )
        dispatch(ctx, "/screenshot")
        assert any("Screenshot saved" in t for t in ctx.ui.texts("success"))

    def test_windows_available(self, ctx, monkeypatch):
        force_available(monkeypatch)

        class FakeController:
            def list_windows(self):
                return "Open windows:\n  - \"Notepad\""

        monkeypatch.setattr(
            "seedcode.tools.desktop.get_controller", lambda: FakeController()
        )
        dispatch(ctx, "/windows")
        assert any("Notepad" in t for t in ctx.ui.texts("panel"))


class TestConfigField:
    def test_desktop_mode_persists_in_model(self):
        config = AppConfig(desktop_mode=True)
        assert AppConfig.model_validate(config.model_dump()).desktop_mode is True

    def test_desktop_mode_defaults_off(self):
        assert AppConfig().desktop_mode is False
