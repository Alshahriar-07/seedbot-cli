"""Tests for the agent loop: detection, execution, validation, retry, finish."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedcode.core.agent import AgentEngine, parse_tool_calls, strip_tool_blocks
from seedcode.core.models import AppConfig
from seedcode.tools import PermissionManager, PermissionMode


def tool_block(payload: str) -> str:
    return f"```tool\n{payload}\n```"


# --- parsing -----------------------------------------------------------------
class TestParsing:
    def test_no_blocks(self):
        assert parse_tool_calls("Just a normal answer.") == []

    def test_single_call(self):
        calls = parse_tool_calls(tool_block('{"tool": "read_file", "args": {"path": "a.py"}}'))
        assert len(calls) == 1
        assert calls[0].tool == "read_file" and calls[0].args == {"path": "a.py"} \
            and not calls[0].error

    def test_multiple_calls(self):
        text = (
            tool_block('{"tool": "list_dir", "args": {}}')
            + "\nthen\n"
            + tool_block('{"tool": "read_file", "args": {"path": "b.py"}}')
        )
        assert [c.tool for c in parse_tool_calls(text)] == ["list_dir", "read_file"]

    def test_malformed_json_reports_error(self):
        calls = parse_tool_calls(tool_block('{"tool": "read_file",'))
        assert len(calls) == 1 and calls[0].error

    def test_missing_tool_name_reports_error(self):
        calls = parse_tool_calls(tool_block('{"args": {}}'))
        assert calls[0].error

    def test_strip_tool_blocks(self):
        text = "Before.\n" + tool_block('{"tool": "list_dir", "args": {}}') + "\nAfter."
        stripped = strip_tool_blocks(text)
        assert "Before." in stripped and "After." in stripped and "```tool" not in stripped


# --- the loop -----------------------------------------------------------------
class ScriptedAgent(AgentEngine):
    """AgentEngine whose 'model' is a scripted list of replies (no network).

    Pins the TEXT protocol path (native tool calling is exercised by
    :class:`NativeScriptedAgent` below).
    """

    def __init__(self, workspace: Path, replies: list[str], mode=PermissionMode.WORKSPACE):
        config = AppConfig()
        config.model = "test-model"
        super().__init__(config, PermissionManager(workspace=workspace, mode=mode))
        self._replies = list(replies)
        self.requests = 0

    def _native_active(self) -> bool:
        return False

    def stream_reply(self):
        self.requests += 1
        if not self._replies:
            pytest.fail("agent asked for more replies than scripted")
        yield self._replies.pop(0)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "hello.txt").write_text("hello world\n", encoding="utf-8")
    return tmp_path


class TestAgentLoop:
    def test_plain_answer_ends_turn(self, workspace):
        agent = ScriptedAgent(workspace, ["All done, no tools needed."])
        assert agent.run_turn("hi") == "All done, no tools needed."
        assert agent.requests == 1

    def test_tool_call_then_answer(self, workspace):
        agent = ScriptedAgent(
            workspace,
            [
                tool_block('{"tool": "read_file", "args": {"path": "hello.txt"}}'),
                "The file says hello world.",
            ],
        )
        final = agent.run_turn("what does hello.txt say?")
        assert "hello world" in final
        assert agent.requests == 2
        # The tool result was fed back as a user-role message.
        feedback = [m for m in agent.messages if m.content.startswith("[TOOL RESULTS]")]
        assert feedback and "hello world" in feedback[0].content

    def test_tool_writes_file(self, workspace):
        agent = ScriptedAgent(
            workspace,
            [
                tool_block('{"tool": "write_file", "args": {"path": "out.txt", "content": "made"}}'),
                "Created out.txt.",
            ],
        )
        agent.run_turn("create out.txt")
        assert (workspace / "out.txt").read_text(encoding="utf-8") == "made"

    def test_malformed_call_is_retried(self, workspace):
        agent = ScriptedAgent(
            workspace,
            [
                tool_block('{"tool": "read_file"'),  # broken JSON -> error fed back
                tool_block('{"tool": "read_file", "args": {"path": "hello.txt"}}'),
                "Recovered.",
            ],
        )
        assert agent.run_turn("read it") == "Recovered."
        assert agent.requests == 3

    def test_permission_denial_reaches_model(self, workspace):
        agent = ScriptedAgent(
            workspace,
            [
                tool_block('{"tool": "write_file", "args": {"path": "x.txt", "content": "no"}}'),
                "I could not write the file (read-only).",
            ],
            mode=PermissionMode.READ_ONLY,
        )
        agent.run_turn("write x.txt")
        assert not (workspace / "x.txt").exists()
        feedback = [m for m in agent.messages if m.content.startswith("[TOOL RESULTS]")]
        assert feedback and "Read Only" in feedback[0].content

    def test_step_budget_bounds_the_loop(self, workspace):
        from seedcode.core import agent as agent_mod

        endless = [tool_block('{"tool": "list_dir", "args": {}}')] * (agent_mod.MAX_STEPS + 1)
        agent = ScriptedAgent(workspace, endless)
        final = agent.run_turn("loop forever")
        assert "step limit" in final
        assert agent.requests == agent_mod.MAX_STEPS

    def test_system_prompt_lists_tools_and_mode(self, workspace):
        agent = ScriptedAgent(workspace, ["ok"])
        prompt = agent.messages[0].content
        assert "read_file" in prompt and "run_command" in prompt
        assert "Workspace" in prompt and str(workspace) in prompt


# --- native tool calling --------------------------------------------------------
from seedcode.core.agent import _downgrade_for_text  # noqa: E402
from seedcode.core.chat import ChatError  # noqa: E402
from seedcode.core.models import Message, ToolCallRecord  # noqa: E402
from seedcode.core.providers.base import TextDelta, ToolCallEvent  # noqa: E402


class NativeScriptedAgent(AgentEngine):
    """AgentEngine with a scripted native event stream (no network).

    Each entry in ``event_replies`` is either a list of StreamEvents (a
    native step) or an Exception to raise. ``text_replies`` back the text
    protocol used after a fallback.
    """

    def __init__(self, workspace: Path, event_replies, text_replies=(),
                 mode=PermissionMode.WORKSPACE):
        config = AppConfig()
        config.model = "test-model"
        super().__init__(config, PermissionManager(workspace=workspace, mode=mode))
        self._event_replies = list(event_replies)
        self._text_replies = list(text_replies)
        self.native_requests = 0
        self.text_requests = 0

    def _native_active(self) -> bool:
        return self._native is not False  # supports_tools == True, no lookup

    def stream_reply_events(self, tools):
        assert tools, "native path must send tool specs"
        self.native_requests += 1
        if not self._event_replies:
            pytest.fail("agent asked for more native replies than scripted")
        item = self._event_replies.pop(0)
        if isinstance(item, Exception):
            raise item
        yield from item

    def stream_reply(self):
        self.text_requests += 1
        if not self._text_replies:
            pytest.fail("agent asked for more text replies than scripted")
        yield self._text_replies.pop(0)


class TestNativeToolCalling:
    def test_native_call_then_answer(self, workspace):
        agent = NativeScriptedAgent(
            workspace,
            [
                [ToolCallEvent(id="c1", name="read_file",
                               arguments={"path": "hello.txt"})],
                [TextDelta("The file says hello world.")],
            ],
        )
        final = agent.run_turn("what does hello.txt say?")
        assert "hello world" in final
        assert agent.native_requests == 2 and agent.text_requests == 0
        # History: assistant with structured calls + a matching tool message.
        assistant = next(m for m in agent.messages if m.tool_calls)
        assert assistant.tool_calls[0].name == "read_file"
        tool_msg = next(m for m in agent.messages if m.role == "tool")
        assert tool_msg.tool_call_id == "c1" and "hello world" in tool_msg.content

    def test_native_write_touches_disk(self, workspace):
        agent = NativeScriptedAgent(
            workspace,
            [
                [ToolCallEvent(id="c1", name="write_file",
                               arguments={"path": "out.txt", "content": "made"})],
                [TextDelta("Created.")],
            ],
        )
        agent.run_turn("create out.txt")
        assert (workspace / "out.txt").read_text(encoding="utf-8") == "made"

    def test_text_protocol_despite_native_mode(self, workspace):
        # Some models emit ```tool blocks even when offered native tools.
        agent = NativeScriptedAgent(
            workspace,
            [
                [TextDelta(tool_block(
                    '{"tool": "read_file", "args": {"path": "hello.txt"}}'
                ))],
                [TextDelta("Done reading.")],
            ],
        )
        assert agent.run_turn("read it") == "Done reading."
        feedback = [m for m in agent.messages if m.content.startswith("[TOOL RESULTS]")]
        assert feedback and "hello world" in feedback[0].content

    def test_first_native_failure_falls_back_to_text(self, workspace):
        agent = NativeScriptedAgent(
            workspace,
            [ChatError("tools are not supported by this model")],
            text_replies=[
                tool_block('{"tool": "read_file", "args": {"path": "hello.txt"}}'),
                "Recovered over text.",
            ],
        )
        assert agent.run_turn("read it") == "Recovered over text."
        assert agent._native is False
        assert agent.native_requests == 1 and agent.text_requests == 2
        # After the downgrade the system prompt carries the manifest again.
        assert "```tool" in agent.messages[0].content

    def test_native_error_after_success_propagates(self, workspace):
        agent = NativeScriptedAgent(
            workspace,
            [
                [ToolCallEvent(id="c1", name="list_dir", arguments={})],
                ChatError("server exploded"),
            ],
        )
        with pytest.raises(ChatError):
            agent.run_turn("list")
        assert agent._native is True  # no silent downgrade after first success

    def test_malformed_native_arguments_fed_back(self, workspace):
        agent = NativeScriptedAgent(
            workspace,
            [
                [ToolCallEvent(id="c1", name="read_file", arguments={},
                               error="Tool call arguments were not valid JSON: x")],
                [TextDelta("Gave up.")],
            ],
        )
        assert agent.run_turn("read") == "Gave up."
        tool_msg = next(m for m in agent.messages if m.role == "tool")
        assert "[ERROR]" in tool_msg.content

    def test_native_prompt_omits_manifest(self, workspace):
        agent = NativeScriptedAgent(workspace, [[TextDelta("ok")]])
        prompt = agent.messages[0].content
        assert "```tool" not in prompt
        assert "AGENT MODE" in prompt and str(workspace) in prompt


class TestDowngradeForText:
    def test_renders_native_history_as_text_protocol(self):
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="do it"),
            Message(
                role="assistant",
                content="Working on it.",
                tool_calls=[ToolCallRecord(id="c1", name="read_file",
                                           arguments={"path": "a.py"})],
            ),
            Message(role="tool", content="[OK] contents", tool_call_id="c1",
                    tool_name="read_file"),
            Message(role="tool", content="[OK] more", tool_call_id="c2",
                    tool_name="list_dir"),
            Message(role="assistant", content="Done."),
        ]
        out = _downgrade_for_text(messages)
        roles = [m.role for m in out]
        assert "tool" not in roles
        assistant = out[2]
        assert "```tool" in assistant.content and '"read_file"' in assistant.content
        merged = out[3]
        assert merged.role == "user" and merged.content.startswith("[TOOL RESULTS]")
        assert "read_file ->" in merged.content and "list_dir ->" in merged.content
        assert out[4].content == "Done."
