"""Tests for the tool engine: permissions, filesystem, search, patch, git."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedcode.tools import (
    PermissionError_,
    PermissionManager,
    PermissionMode,
    TOOL_REGISTRY,
    get_tool,
    tool_manifest,
)
from seedcode.tools.filesystem import build_index


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n# TODO: fix\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    return tmp_path


def make_perm(workspace: Path, mode: PermissionMode = PermissionMode.WORKSPACE):
    return PermissionManager(workspace=workspace, mode=mode)


def run(perm, name: str, **args):
    return get_tool(name).run(perm, args)


# --- permissions -------------------------------------------------------------
class TestPermissions:
    def test_parse_aliases(self):
        assert PermissionMode.parse("read-only") is PermissionMode.READ_ONLY
        assert PermissionMode.parse("Workspace") is PermissionMode.WORKSPACE
        assert PermissionMode.parse("full") is PermissionMode.FULL_ACCESS
        with pytest.raises(ValueError):
            PermissionMode.parse("everything")

    def test_read_only_blocks_writes(self, workspace):
        perm = make_perm(workspace, PermissionMode.READ_ONLY)
        with pytest.raises(PermissionError_):
            perm.check_write(workspace / "x.txt")
        with pytest.raises(PermissionError_):
            perm.check_execute("ls")

    def test_workspace_blocks_outside_paths(self, workspace, tmp_path_factory):
        outside = tmp_path_factory.mktemp("elsewhere") / "x.txt"
        perm = make_perm(workspace)
        with pytest.raises(PermissionError_):
            perm.check_write(outside)
        perm.check_write(workspace / "inside.txt")  # no raise

    def test_full_access_allows_outside(self, workspace, tmp_path_factory):
        outside = tmp_path_factory.mktemp("elsewhere") / "x.txt"
        perm = make_perm(workspace, PermissionMode.FULL_ACCESS)
        perm.check_write(outside)  # no raise

    def test_relative_paths_anchor_at_workspace(self, workspace):
        perm = make_perm(workspace)
        assert perm.resolve("src/main.py") == (workspace / "src" / "main.py").resolve()

    def test_traversal_escapes_are_blocked(self, workspace):
        perm = make_perm(workspace)
        with pytest.raises(PermissionError_):
            perm.check_write(perm.resolve("../escape.txt"))


# --- filesystem ----------------------------------------------------------------
class TestFilesystem:
    def test_read_file(self, workspace):
        result = run(make_perm(workspace), "read_file", path="src/main.py")
        assert result.ok and "print('hello')" in result.output

    def test_read_missing_file(self, workspace):
        result = run(make_perm(workspace), "read_file", path="nope.py")
        assert not result.ok

    def test_write_and_delete(self, workspace):
        perm = make_perm(workspace)
        assert run(perm, "write_file", path="new/thing.txt", content="hi").ok
        assert (workspace / "new" / "thing.txt").read_text(encoding="utf-8") == "hi"
        assert run(perm, "delete_file", path="new/thing.txt").ok
        assert not (workspace / "new" / "thing.txt").exists()

    def test_write_blocked_read_only(self, workspace):
        perm = make_perm(workspace, PermissionMode.READ_ONLY)
        with pytest.raises(PermissionError_):
            run(perm, "write_file", path="x.txt", content="no")

    def test_delete_refuses_directory(self, workspace):
        result = run(make_perm(workspace), "delete_file", path="src")
        assert not result.ok and "directory" in result.output

    def test_list_dir(self, workspace):
        result = run(make_perm(workspace), "list_dir")
        assert result.ok and "README.md" in result.output

    def test_index(self, workspace):
        tree = build_index(make_perm(workspace))
        assert "src/" in tree and "main.py" in tree
        assert "__pycache__" not in tree


# --- search --------------------------------------------------------------------
class TestSearch:
    def test_find_files(self, workspace):
        result = run(make_perm(workspace), "find_files", pattern="*.py")
        assert result.ok and "main.py" in result.output

    def test_search_text(self, workspace):
        result = run(make_perm(workspace), "search_text", pattern="TODO")
        assert result.ok and "main.py:2" in result.output.replace("\\", "/")

    def test_search_bad_regex(self, workspace):
        result = run(make_perm(workspace), "search_text", pattern="[unclosed")
        assert not result.ok


# --- patch ---------------------------------------------------------------------
class TestPatch:
    def test_edit_exact_once(self, workspace):
        perm = make_perm(workspace)
        result = run(
            perm, "edit_file", path="src/main.py",
            old_text="# TODO: fix", new_text="# done",
        )
        assert result.ok
        assert "# done" in (workspace / "src" / "main.py").read_text(encoding="utf-8")

    def test_edit_rejects_missing_text(self, workspace):
        result = run(
            make_perm(workspace), "edit_file", path="src/main.py",
            old_text="not there", new_text="x",
        )
        assert not result.ok and "not found" in result.output

    def test_edit_rejects_ambiguous_match(self, workspace):
        (workspace / "dup.txt").write_text("aaa\naaa\n", encoding="utf-8")
        result = run(
            make_perm(workspace), "edit_file", path="dup.txt",
            old_text="aaa", new_text="bbb",
        )
        assert not result.ok and "2 times" in result.output


# --- terminal & git --------------------------------------------------------------
class TestTerminalAndGit:
    def test_run_command(self, workspace):
        result = run(make_perm(workspace), "run_command", command="echo seed")
        assert result.ok and "seed" in result.output

    def test_run_command_blocked_read_only(self, workspace):
        perm = make_perm(workspace, PermissionMode.READ_ONLY)
        with pytest.raises(PermissionError_):
            run(perm, "run_command", command="echo x")

    def test_run_command_failure_reported(self, workspace):
        result = run(make_perm(workspace), "run_command", command="exit 3")
        assert not result.ok and "exit code 3" in result.output

    def test_git_rejects_unknown_subcommand(self, workspace):
        # push/pull/fetch are now allowed (gated); truly unknown ones refuse.
        result = run(make_perm(workspace), "git", args="filter-branch --all")
        assert not result.ok and "not allowed" in result.output

    def test_git_read_allowed_in_read_only(self, workspace):
        # status is a read subcommand: permitted even in read-only mode
        # (result may fail because tmp dir isn't a repo — that's fine).
        perm = make_perm(workspace, PermissionMode.READ_ONLY)
        run(perm, "git", args="status")

    def test_git_write_blocked_in_read_only(self, workspace):
        perm = make_perm(workspace, PermissionMode.READ_ONLY)
        with pytest.raises(PermissionError_):
            run(perm, "git", args="commit -m x")


# --- registry --------------------------------------------------------------------
class TestRegistry:
    def test_expected_tools_registered(self):
        expected = {
            "read_file", "write_file", "edit_file", "delete_file", "list_dir",
            "find_files", "search_text", "run_command", "git", "project_index",
        }
        assert expected <= set(TOOL_REGISTRY)

    def test_manifest_mentions_every_tool(self):
        manifest = tool_manifest(("core", "desktop"))
        for name in TOOL_REGISTRY:
            assert name in manifest

    def test_default_manifest_is_core_only(self):
        manifest = tool_manifest()
        for name, tool in TOOL_REGISTRY.items():
            assert (name in manifest) == (tool.group == "core")

    def test_missing_required_arg_raises(self, workspace):
        from seedcode.tools import ToolError

        with pytest.raises(ToolError):
            run(make_perm(workspace), "read_file")
