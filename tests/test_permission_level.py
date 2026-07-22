"""Tests for the unified hierarchical permission model and config migration."""

from __future__ import annotations

import pytest

from seedcode.core.models import AppConfig
from seedcode.tools.permissions import (
    PermissionError_,
    PermissionLevel,
    PermissionManager,
    PermissionMode,
)


# --- hierarchy ----------------------------------------------------------------
class TestHierarchy:
    def test_levels_are_ordered(self):
        assert (
            PermissionLevel.READ_ONLY
            < PermissionLevel.WORKSPACE
            < PermissionLevel.DESKTOP
            < PermissionLevel.FULL_SYSTEM
        )

    def test_legacy_alias_full_access(self):
        # Old code/config said FULL_ACCESS; it is the same level as FULL_SYSTEM.
        assert PermissionLevel.FULL_ACCESS == PermissionLevel.FULL_SYSTEM
        assert PermissionMode is PermissionLevel  # one enum, two names

    def test_parse_aliases(self):
        assert PermissionLevel.parse("read_only") is PermissionLevel.READ_ONLY
        assert PermissionLevel.parse("workspace") is PermissionLevel.WORKSPACE
        assert PermissionLevel.parse("desktop") is PermissionLevel.DESKTOP
        assert PermissionLevel.parse("full_system") == PermissionLevel.FULL_SYSTEM
        assert PermissionLevel.parse("full_access") == PermissionLevel.FULL_SYSTEM
        assert PermissionLevel.parse(PermissionLevel.DESKTOP) is PermissionLevel.DESKTOP
        with pytest.raises(ValueError):
            PermissionLevel.parse("supreme")

    def test_value_str_and_labels(self):
        assert PermissionLevel.DESKTOP.value_str == "desktop"
        assert PermissionLevel.FULL_SYSTEM.value_str == "full_system"
        assert PermissionLevel.FULL_SYSTEM.label == "Full System"

    def test_allows_desktop(self):
        assert not PermissionLevel.READ_ONLY.allows_desktop
        assert not PermissionLevel.WORKSPACE.allows_desktop
        assert PermissionLevel.DESKTOP.allows_desktop
        assert PermissionLevel.FULL_SYSTEM.allows_desktop


# --- require() ----------------------------------------------------------------
class TestRequire:
    def test_sufficient_level_passes(self, tmp_path):
        perm = PermissionManager(workspace=tmp_path, level=PermissionLevel.DESKTOP)
        perm.require(PermissionLevel.WORKSPACE)
        perm.require(PermissionLevel.DESKTOP)
        perm.require("desktop", "drive the computer")

    def test_insufficient_level_blocks_with_hint(self, tmp_path):
        perm = PermissionManager(workspace=tmp_path, level=PermissionLevel.WORKSPACE)
        with pytest.raises(PermissionError_, match="Desktop"):
            perm.require(PermissionLevel.DESKTOP, "drive the computer")
        with pytest.raises(PermissionError_, match="Full System"):
            perm.require(PermissionLevel.FULL_SYSTEM)

    def test_legacy_mode_kwarg_still_works(self, tmp_path):
        perm = PermissionManager(workspace=tmp_path, mode=PermissionMode.WORKSPACE)
        assert perm.level is PermissionLevel.WORKSPACE
        assert perm.mode is PermissionLevel.WORKSPACE  # alias property

    def test_write_gates_by_level(self, tmp_path, tmp_path_factory):
        outside = tmp_path_factory.mktemp("elsewhere") / "x.txt"
        read_only = PermissionManager(workspace=tmp_path, level=PermissionLevel.READ_ONLY)
        with pytest.raises(PermissionError_):
            read_only.check_write(tmp_path / "a.txt")
        ws = PermissionManager(workspace=tmp_path, level=PermissionLevel.WORKSPACE)
        ws.check_write(tmp_path / "a.txt")  # inside: fine
        with pytest.raises(PermissionError_):
            ws.check_write(outside)  # outside needs full_system
        desktop = PermissionManager(workspace=tmp_path, level=PermissionLevel.DESKTOP)
        with pytest.raises(PermissionError_):
            desktop.check_write(outside)  # desktop still can't write outside


# --- config migration ---------------------------------------------------------
class TestConfigMigration:
    def test_legacy_full_access_renames(self):
        config = AppConfig.model_validate({"permission_mode": "full_access"})
        assert config.permission_mode == "full_system"

    def test_legacy_desktop_mode_elevates_workspace(self):
        config = AppConfig.model_validate(
            {"permission_mode": "workspace", "desktop_mode": True}
        )
        assert config.permission_mode == "desktop"
        assert config.desktop_mode is True  # derived property

    def test_legacy_desktop_mode_with_full_access(self):
        config = AppConfig.model_validate(
            {"permission_mode": "full_access", "desktop_mode": True}
        )
        assert config.permission_mode == "full_system"

    def test_desktop_mode_false_does_not_elevate(self):
        config = AppConfig.model_validate(
            {"permission_mode": "workspace", "desktop_mode": False}
        )
        assert config.permission_mode == "workspace"
        assert config.desktop_mode is False

    def test_desktop_mode_dropped_from_serialised_config(self):
        config = AppConfig.model_validate({"desktop_mode": True})
        dumped = config.model_dump()
        assert "desktop_mode" not in dumped
        # And the migrated shape round-trips unchanged.
        assert AppConfig.model_validate(dumped).permission_mode == config.permission_mode

    def test_desktop_mode_property_setter(self):
        config = AppConfig()
        assert config.permission_mode == "workspace"
        config.desktop_mode = True
        assert config.permission_mode == "desktop"
        config.desktop_mode = False
        assert config.permission_mode == "workspace"
        # Full System keeps its level when desktop is "enabled" again.
        config.permission_mode = "full_system"
        config.desktop_mode = True
        assert config.permission_mode == "full_system"
