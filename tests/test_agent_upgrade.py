"""Tests for the agent-upgrade additions: streaming terminal, textio,
new filesystem tools, path globs, insert_in_file, and project detection."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from seedcode.core.project import detect_project
from seedcode.tools import PermissionManager, ToolError, get_tool
from seedcode.tools.base import int_arg, tool_specs
from seedcode.tools.terminal import run_command
from seedcode.tools.textio import read_text_file, write_text_file


@pytest.fixture()
def perm(tmp_path: Path) -> PermissionManager:
    return PermissionManager(workspace=tmp_path)


# --- int_arg -------------------------------------------------------------------
class TestIntArg:
    def test_accepts_int_and_numeric_string(self):
        assert int_arg({"n": 5}, "n", 1, 1, 10) == 5
        assert int_arg({"n": "7"}, "n", 1, 1, 10) == 7

    def test_default_and_clamping(self):
        assert int_arg({}, "n", 3, 1, 10) == 3
        assert int_arg({"n": 99}, "n", 1, 1, 10) == 10
        assert int_arg({"n": -5}, "n", 1, 1, 10) == 1

    def test_junk_raises_friendly_error(self):
        with pytest.raises(ToolError, match="whole number"):
            int_arg({"n": "lots"}, "n", 1, 1, 10)


# --- streaming terminal ----------------------------------------------------------
class TestStreamingTerminal:
    def test_lines_stream_through_callback(self, perm):
        seen: list[str] = []
        code = "import sys; print('alpha'); print('beta')"
        result = run_command(
            perm, f'"{sys.executable}" -c "{code}"', 30, on_line=seen.append
        )
        assert result.ok
        assert any("alpha" in line for line in seen)
        assert any("beta" in line for line in seen)
        assert "alpha" in result.output and "beta" in result.output

    def test_nonzero_exit_is_failure(self, perm):
        result = run_command(perm, f'"{sys.executable}" -c "raise SystemExit(3)"', 30)
        assert not result.ok and "exit code 3" in result.output

    def test_timeout_kills_the_process(self, perm):
        start = time.monotonic()
        result = run_command(
            perm, f'"{sys.executable}" -c "import time; time.sleep(30)"', 1
        )
        assert not result.ok and "timed out" in result.output.lower()
        assert time.monotonic() - start < 15  # killed, not waited out

    def test_unknown_shell_is_friendly(self, perm):
        result = run_command(perm, "echo hi", 10, shell="fish")
        assert not result.ok
        assert "cmd" in result.output and "powershell" in result.output

    def test_explicit_shell_runs(self, perm):
        shell = "cmd" if sys.platform == "win32" else "bash"
        result = run_command(perm, "echo streamed", 30, shell=shell)
        assert result.ok and "streamed" in result.output

    def test_run_command_tool_validates_timeout(self, perm):
        result_error = None
        try:
            get_tool("run_command").run(perm, {"command": "echo hi", "timeout": "soon"})
        except ToolError as exc:
            result_error = str(exc)
        assert result_error and "whole number" in result_error


# --- textio -----------------------------------------------------------------------
class TestTextIO:
    def test_crlf_preserved(self, tmp_path):
        target = tmp_path / "crlf.txt"
        target.write_bytes(b"one\r\ntwo\r\nthree\r\n")
        tf = read_text_file(target)
        assert tf.newline == "\r\n" and "\r" not in tf.text
        tf.text = tf.text.replace("two", "2")
        write_text_file(target, tf)
        assert target.read_bytes() == b"one\r\n2\r\nthree\r\n"

    def test_bom_preserved(self, tmp_path):
        target = tmp_path / "bom.txt"
        target.write_bytes(b"\xef\xbb\xbfhello\n")
        tf = read_text_file(target)
        assert tf.encoding == "utf-8-sig" and tf.text == "hello\n"
        write_text_file(target, tf)
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_latin1_round_trip(self, tmp_path):
        target = tmp_path / "latin.txt"
        target.write_bytes(b"caf\xe9\n")  # é in latin-1, invalid UTF-8
        tf = read_text_file(target)
        assert tf.encoding == "latin-1" and "café" in tf.text
        write_text_file(target, tf)
        assert target.read_bytes() == b"caf\xe9\n"

    def test_edit_file_preserves_crlf_and_encoding(self, perm, tmp_path):
        target = tmp_path / "code.py"
        target.write_bytes(b"a = 1\r\nb = 2\r\n")
        result = get_tool("edit_file").run(
            perm, {"path": "code.py", "old_text": "b = 2", "new_text": "b = 20"}
        )
        assert result.ok
        assert target.read_bytes() == b"a = 1\r\nb = 20\r\n"


# --- new filesystem tools -----------------------------------------------------------
class TestNewFilesystemTools:
    def test_append_file_appends_and_creates(self, perm, tmp_path):
        (tmp_path / "log.txt").write_text("first\n", encoding="utf-8")
        result = get_tool("append_file").run(
            perm, {"path": "log.txt", "content": "second\n"}
        )
        assert result.ok
        assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "first\nsecond\n"
        # Missing file is created.
        result = get_tool("append_file").run(perm, {"path": "new.txt", "content": "x"})
        assert result.ok and (tmp_path / "new.txt").read_text(encoding="utf-8") == "x"

    def test_append_preserves_crlf(self, perm, tmp_path):
        target = tmp_path / "win.txt"
        target.write_bytes(b"a\r\n")
        get_tool("append_file").run(perm, {"path": "win.txt", "content": "b\n"})
        assert target.read_bytes() == b"a\r\nb\r\n"

    def test_create_directory(self, perm, tmp_path):
        result = get_tool("create_directory").run(perm, {"path": "pkg/sub"})
        assert result.ok and (tmp_path / "pkg" / "sub").is_dir()
        # Idempotent.
        again = get_tool("create_directory").run(perm, {"path": "pkg/sub"})
        assert again.ok and "already existed" in again.output

    def test_rename_file(self, perm, tmp_path):
        (tmp_path / "old.txt").write_text("data", encoding="utf-8")
        result = get_tool("rename_file").run(
            perm, {"path": "old.txt", "new_name": "new.txt"}
        )
        assert result.ok
        assert not (tmp_path / "old.txt").exists()
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "data"

    def test_rename_refuses_paths_and_overwrite(self, perm, tmp_path):
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        assert not get_tool("rename_file").run(
            perm, {"path": "a.txt", "new_name": "sub/b.txt"}
        ).ok
        assert not get_tool("rename_file").run(
            perm, {"path": "a.txt", "new_name": "b.txt"}
        ).ok

    def test_move_file(self, perm, tmp_path):
        (tmp_path / "src.txt").write_text("data", encoding="utf-8")
        result = get_tool("move_file").run(
            perm, {"path": "src.txt", "destination": "deep/dir/dst.txt"}
        )
        assert result.ok
        assert (tmp_path / "deep" / "dir" / "dst.txt").read_text(encoding="utf-8") == "data"

    def test_move_into_existing_directory(self, perm, tmp_path):
        (tmp_path / "f.txt").write_text("data", encoding="utf-8")
        (tmp_path / "folder").mkdir()
        result = get_tool("move_file").run(
            perm, {"path": "f.txt", "destination": "folder"}
        )
        assert result.ok and (tmp_path / "folder" / "f.txt").exists()


# --- path globs ------------------------------------------------------------------
class TestPathGlobs:
    @pytest.fixture()
    def tree(self, perm, tmp_path):
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "docs").mkdir()
        (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "util.py").write_text("", encoding="utf-8")
        (tmp_path / "docs" / "notes.md").write_text("", encoding="utf-8")
        (tmp_path / "top.py").write_text("", encoding="utf-8")
        return perm

    def test_name_glob_still_works(self, tree):
        result = get_tool("find_files").run(tree, {"pattern": "*.py"})
        assert "main.py" in result.output and "util.py" in result.output \
            and "top.py" in result.output

    def test_recursive_path_glob(self, tree):
        result = get_tool("find_files").run(tree, {"pattern": "src/**/*.py"})
        assert "main.py" in result.output and "util.py" in result.output
        assert "top.py" not in result.output and "notes.md" not in result.output

    def test_single_level_path_glob(self, tree):
        result = get_tool("find_files").run(tree, {"pattern": "src/*.py"})
        assert "main.py" in result.output and "util.py" not in result.output


# --- insert_in_file -----------------------------------------------------------------
class TestInsertInFile:
    @pytest.fixture()
    def target(self, tmp_path):
        (tmp_path / "mod.py").write_text("import os\n\ndef go():\n    pass\n", encoding="utf-8")
        return tmp_path / "mod.py"

    def test_insert_after(self, perm, target):
        result = get_tool("insert_in_file").run(
            perm,
            {"path": "mod.py", "anchor": "import os\n", "position": "after",
             "text": "import sys\n"},
        )
        assert result.ok
        assert target.read_text(encoding="utf-8").startswith("import os\nimport sys\n")

    def test_insert_before(self, perm, target):
        result = get_tool("insert_in_file").run(
            perm,
            {"path": "mod.py", "anchor": "def go():", "position": "before",
             "text": "# entry\n"},
        )
        assert result.ok
        assert "# entry\ndef go():" in target.read_text(encoding="utf-8")

    def test_ambiguous_anchor_refused(self, perm, target):
        target.write_text("x = 1\nx = 1\n", encoding="utf-8")
        result = get_tool("insert_in_file").run(
            perm,
            {"path": "mod.py", "anchor": "x = 1", "position": "after", "text": "y"},
        )
        assert not result.ok and "2 times" in result.output

    def test_missing_anchor_refused(self, perm, target):
        result = get_tool("insert_in_file").run(
            perm,
            {"path": "mod.py", "anchor": "not here", "position": "after", "text": "y"},
        )
        assert not result.ok and "not found" in result.output

    def test_bad_position_refused(self, perm, target):
        result = get_tool("insert_in_file").run(
            perm,
            {"path": "mod.py", "anchor": "import os", "position": "around", "text": "y"},
        )
        assert not result.ok and "before" in result.output


# --- tool_specs -----------------------------------------------------------------------
class TestToolSpecs:
    def test_specs_cover_core_registry(self):
        specs = {s["name"] for s in tool_specs(("core",))}
        for name in ("read_file", "write_file", "edit_file", "append_file",
                     "rename_file", "move_file", "create_directory", "run_command",
                     "git", "find_files", "search_text", "insert_in_file"):
            assert name in specs

    def test_required_and_types(self):
        spec = next(s for s in tool_specs(("core",)) if s["name"] == "read_file")
        params = spec["parameters"]
        assert params["required"] == ["path"]
        assert params["properties"]["start_line"]["type"] == "integer"
        assert params["properties"]["path"]["type"] == "string"


# --- project detection ------------------------------------------------------------------
class TestProjectDetection:
    def test_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (tmp_path / "main.py").write_text("", encoding="utf-8")
        info = detect_project(tmp_path)
        assert any("Python" in k for k in info.kinds)
        assert "main.py" in info.summary

    def test_git_branch_from_head(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/feature/x\n", encoding="utf-8")
        info = detect_project(tmp_path)
        assert any("feature/x" in k for k in info.kinds)

    def test_node_and_rust_markers(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
        info = detect_project(tmp_path)
        assert any("Node.js" in k for k in info.kinds)
        assert any("Rust" in k for k in info.kinds)

    def test_empty_workspace_is_fine(self, tmp_path):
        info = detect_project(tmp_path)
        assert info.kinds == []
        assert "empty workspace" in info.summary
