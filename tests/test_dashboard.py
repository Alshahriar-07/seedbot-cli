"""Startup dashboard rendering tests: no network, no real terminal."""

from __future__ import annotations

from rich.console import Console

from seedcode.core.models import AppConfig
from seedcode.ui.dashboard import render_dashboard
from seedcode.ui.theme import SEED_THEME


def _render(config: AppConfig, width: int) -> str:
    console = Console(
        theme=SEED_THEME,
        width=width,
        force_terminal=True,
        legacy_windows=False,
        record=True,
        highlight=False,
    )
    render_dashboard(console, config)
    return console.export_text()


def _configured() -> AppConfig:
    cfg = AppConfig()  # active provider is freemodel_claude by default
    cfg.set_api_key("freemodel_claude", "fe_oa_test")
    cfg.model = "claude-opus-4.1"
    return cfg


def test_wide_two_column_layout() -> None:
    out = _render(_configured(), width=140)
    assert "Seed Code v" in out
    assert "Current Session" in out
    assert "Plant ideas. Grow code." in out
    assert "Created by Al Shahriar Sowan" in out
    assert "FreeModel Claude" in out
    assert "Claude API" in out
    assert "claude-opus-4.1" in out
    # Two-column: the logo and session block share at least one line.
    assert any("██" in line and "Provider" in line for line in out.splitlines())


def test_codex_backend_label() -> None:
    cfg = AppConfig(provider="freemodel_codex")
    cfg.set_api_key("freemodel_codex", "fe_oa_test")
    cfg.model = "gpt-5.1-codex"
    out = _render(cfg, width=140)
    assert "FreeModel Codex" in out
    assert "Responses API" in out
    assert "gpt-5.1-codex" in out


def test_narrow_stacks_session_below_logo() -> None:
    out = _render(_configured(), width=80)
    lines = out.splitlines()
    # Stacked: no line contains both logo art and session fields.
    assert not any("███" in line and "Provider" in line for line in lines)
    assert "Current Session" in out
    assert "claude-opus-4.1" in out
    # Nothing overlaps/overflows the requested width.
    assert all(len(line) <= 80 for line in lines)


def test_unconfigured_placeholders() -> None:
    out = _render(AppConfig(), width=140)
    assert "Not selected" in out
    assert "Not configured" in out
    assert "--" in out
    assert "History" in out and "Enabled" in out


def test_no_line_exceeds_terminal_width() -> None:
    for width in (60, 90, 120, 200):
        out = _render(_configured(), width=width)
        assert all(len(line) <= width for line in out.splitlines()), width
