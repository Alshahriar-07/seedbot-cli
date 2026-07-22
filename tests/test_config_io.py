"""Config load/save fault-tolerance tests using temp paths: no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedcode.config import manager


@pytest.fixture(autouse=True)
def _no_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env API keys must not leak into these tests."""
    for names in manager.ENV_KEYS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


def _use_config_file(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(manager, "config_path", lambda: path)


def test_missing_config_yields_defaults(tmp_path: Path, monkeypatch) -> None:
    _use_config_file(monkeypatch, tmp_path / "config.json")
    cfg = manager.load_config()
    assert cfg.active_provider == "freemodel_claude"
    assert not cfg.is_configured()


def test_corrupt_config_falls_back_to_defaults(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text("{this is not json", encoding="utf-8")
    _use_config_file(monkeypatch, path)
    cfg = manager.load_config()  # must not raise
    assert cfg.active_provider == "freemodel_claude"


def test_save_and_load_round_trip(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    _use_config_file(monkeypatch, path)
    cfg = manager.load_config()
    cfg.set_api_key("aerolink", "al-key")
    cfg.provider = "aerolink"
    cfg.model = "claude-x"
    manager.save_config(cfg)

    loaded = manager.load_config()
    assert loaded == cfg
    assert loaded.providers["aerolink"].api_key == "al-key"


def test_save_config_never_raises_on_disk_error(tmp_path: Path, monkeypatch) -> None:
    # Point the "file" at an existing DIRECTORY: write_text raises OSError.
    _use_config_file(monkeypatch, tmp_path)
    cfg = manager.load_config()
    manager.save_config(cfg)  # must swallow the failure, not crash


def test_env_var_overrides_stored_key(tmp_path: Path, monkeypatch) -> None:
    _use_config_file(monkeypatch, tmp_path / "config.json")
    monkeypatch.setenv("FREEMODEL_API_KEY", "fe_oa_from_env")
    cfg = manager.load_config()
    # One FreeModel account key applies to BOTH FreeModel providers.
    assert cfg.get_api_key("freemodel_claude") == "fe_oa_from_env"
    assert cfg.get_api_key("freemodel_codex") == "fe_oa_from_env"
