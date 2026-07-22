"""Tests for the dangerous-action Y/A/N confirmation gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedcode.tools import PermissionError_, PermissionManager, PermissionMode, get_tool
from seedcode.tools.permissions import (
    ACTION_LABELS,
    CATEGORY_DELETE,
    CATEGORY_GIT_MUTATE,
    CATEGORY_OUTSIDE_WRITE,
    CATEGORY_SHELL,
    ActionGate,
    ActionGrant,
)


class ScriptedConfirm:
    """Confirm callback answering from a script and recording prompts."""

    def __init__(self, answers: list[ActionGrant]):
        self.answers = list(answers)
        self.prompts: list[tuple[str, str]] = []

    def __call__(self, category: str, description: str) -> ActionGrant:
        self.prompts.append((category, description))
        if not self.answers:
            pytest.fail("gate prompted more times than scripted")
        return self.answers.pop(0)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "doomed.txt").write_text("bye\n", encoding="utf-8")
    return tmp_path


def manager(workspace: Path, confirm, mode=PermissionMode.WORKSPACE) -> PermissionManager:
    perm = PermissionManager(workspace=workspace, mode=mode)
    perm.gate = ActionGate(confirm=confirm)
    return perm


class TestActionGate:
    def test_once_reprompts_every_time(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.ONCE, ActionGrant.ONCE])
        perm = manager(workspace, confirm)
        perm.confirm_action(CATEGORY_SHELL, "echo 1")
        perm.confirm_action(CATEGORY_SHELL, "echo 2")
        assert len(confirm.prompts) == 2

    def test_always_is_remembered_per_category(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.ALWAYS, ActionGrant.ONCE])
        perm = manager(workspace, confirm)
        perm.confirm_action(CATEGORY_SHELL, "echo 1")
        perm.confirm_action(CATEGORY_SHELL, "echo 2")  # no prompt
        assert len(confirm.prompts) == 1
        # A different category still prompts.
        perm.confirm_action(CATEGORY_DELETE, "x.txt")
        assert len(confirm.prompts) == 2

    def test_deny_raises_and_sticks(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm)
        with pytest.raises(PermissionError_):
            perm.confirm_action(CATEGORY_SHELL, "rm -rf /")
        # Second attempt raises WITHOUT prompting again.
        with pytest.raises(PermissionError_):
            perm.confirm_action(CATEGORY_SHELL, "rm -rf /")
        assert len(confirm.prompts) == 1

    def test_no_gate_means_no_prompt(self, workspace):
        perm = PermissionManager(workspace=workspace)
        perm.confirm_action(CATEGORY_SHELL, "echo ok")  # must not raise

    def test_reset_forgets_grants(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.ALWAYS, ActionGrant.ONCE])
        perm = manager(workspace, confirm)
        perm.confirm_action(CATEGORY_SHELL, "echo 1")
        perm.gate.reset()
        perm.confirm_action(CATEGORY_SHELL, "echo 2")
        assert len(confirm.prompts) == 2

    def test_every_category_has_a_label(self):
        for category in (
            CATEGORY_SHELL, CATEGORY_GIT_MUTATE, CATEGORY_DELETE, CATEGORY_OUTSIDE_WRITE
        ):
            assert category in ACTION_LABELS


class TestGateHookPoints:
    """Denials raise PermissionError_ from the tool runner (the agent loop
    converts that into a failed ToolResult for the model)."""

    def test_run_command_prompts(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm)
        with pytest.raises(PermissionError_):
            get_tool("run_command").run(perm, {"command": "echo hi"})
        assert confirm.prompts[0][0] == CATEGORY_SHELL

    def test_delete_file_prompts(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm)
        with pytest.raises(PermissionError_):
            get_tool("delete_file").run(perm, {"path": "doomed.txt"})
        assert (workspace / "doomed.txt").exists()
        assert confirm.prompts[0][0] == CATEGORY_DELETE

    def test_delete_file_allowed_once(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.ONCE])
        perm = manager(workspace, confirm)
        result = get_tool("delete_file").run(perm, {"path": "doomed.txt"})
        assert result.ok
        assert not (workspace / "doomed.txt").exists()

    def test_git_commit_prompts_and_deny_blocks(self, workspace):
        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm)
        with pytest.raises(PermissionError_):
            get_tool("git").run(perm, {"args": 'commit -m "msg"'})
        assert confirm.prompts[0][0] == CATEGORY_GIT_MUTATE
        assert 'git commit -m "msg"' in confirm.prompts[0][1]

    def test_git_push_prompts_remote_category(self, workspace):
        from seedcode.tools.permissions import CATEGORY_GIT_REMOTE

        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm)
        with pytest.raises(PermissionError_):  # denied before any network I/O
            get_tool("git").run(perm, {"args": "push origin main"})
        assert confirm.prompts[0][0] == CATEGORY_GIT_REMOTE

    def test_git_status_never_prompts(self, workspace):
        confirm = ScriptedConfirm([])
        perm = manager(workspace, confirm)
        get_tool("git").run(perm, {"args": "status"})
        assert confirm.prompts == []

    def test_workspace_write_never_prompts(self, workspace):
        confirm = ScriptedConfirm([])
        perm = manager(workspace, confirm)
        result = get_tool("write_file").run(
            perm, {"path": "new.txt", "content": "fine"}
        )
        assert result.ok and confirm.prompts == []

    def test_outside_write_prompts_in_full_access(self, workspace, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside") / "far.txt"
        confirm = ScriptedConfirm([ActionGrant.DENY])
        perm = manager(workspace, confirm, mode=PermissionMode.FULL_ACCESS)
        with pytest.raises(PermissionError_):
            get_tool("write_file").run(perm, {"path": str(outside), "content": "x"})
        assert not outside.exists()
        assert confirm.prompts[0][0] == CATEGORY_OUTSIDE_WRITE
