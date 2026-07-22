"""Tests for native tool calling at the provider layer: streamed event
assembly (canned SSE/NDJSON/SDK chunks) and history serialization."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from seedcode.core.models import Message, ToolCallRecord
from seedcode.core.providers.base import TextDelta, ToolCallEvent


# --- shared fixtures ------------------------------------------------------------
def history_with_tools() -> list[Message]:
    """A canonical native-era transcript: user -> assistant(calls) -> results."""
    return [
        Message(role="system", content="sys"),
        Message(role="user", content="do it"),
        Message(
            role="assistant",
            content="Working.",
            tool_calls=[
                ToolCallRecord(id="c1", name="read_file", arguments={"path": "a.py"}),
                ToolCallRecord(id="c2", name="list_dir", arguments={}),
            ],
        ),
        Message(role="tool", content="[OK] data", tool_call_id="c1", tool_name="read_file"),
        Message(role="tool", content="[OK] listing", tool_call_id="c2", tool_name="list_dir"),
        Message(role="assistant", content="Done."),
    ]


class FakeSSEResponse:
    """Stands in for httpx.Response inside the SSE parsers."""

    def __init__(self, events: list[dict]):
        self._events = events

    def iter_lines(self):
        for event in self._events:
            yield "data: " + json.dumps(event)


# --- Anthropic-style (aerolink + freemodel claude) ---------------------------------
ANTHROPIC_TOOL_EVENTS = [
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": "Let me check."}},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": '{"pa'}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": 'th": "a.py"}'}},
    {"type": "content_block_stop", "index": 1},
]


@pytest.mark.parametrize(
    "parser_import",
    [
        "seedcode.core.providers.aerolink._iter_sse_events",
        "seedcode.core.providers.freemodel._iter_claude_events",
    ],
)
class TestAnthropicEventAssembly:
    def _parser(self, parser_import):
        module_name, func_name = parser_import.rsplit(".", 1)
        module = __import__(module_name, fromlist=[func_name])
        return getattr(module, func_name)

    def test_fragmented_arguments_assemble(self, parser_import):
        events = list(self._parser(parser_import)(FakeSSEResponse(ANTHROPIC_TOOL_EVENTS)))
        assert events[0] == TextDelta("Let me check.")
        call = events[1]
        assert isinstance(call, ToolCallEvent)
        assert call.id == "toolu_1" and call.name == "read_file"
        assert call.arguments == {"path": "a.py"} and not call.error

    def test_broken_argument_json_carries_error(self, parser_import):
        broken = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "t", "name": "read_file"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"path": '}},
            {"type": "content_block_stop", "index": 0},
        ]
        events = list(self._parser(parser_import)(FakeSSEResponse(broken)))
        assert len(events) == 1 and events[0].error and events[0].arguments == {}


@pytest.mark.parametrize(
    "turns_import",
    [
        "seedcode.core.providers.aerolink._to_anthropic_turns",
        "seedcode.core.providers.freemodel._to_claude_turns",
    ],
)
class TestAnthropicSerialization:
    def _func(self, turns_import):
        module_name, func_name = turns_import.rsplit(".", 1)
        module = __import__(module_name, fromlist=[func_name])
        return getattr(module, func_name)

    def test_wire_shape(self, turns_import):
        turns = self._func(turns_import)(history_with_tools())
        # system dropped; assistant carries text + tool_use blocks.
        assert turns[0] == {"role": "user", "content": "do it"}
        assistant = turns[1]
        assert assistant["role"] == "assistant"
        types = [block["type"] for block in assistant["content"]]
        assert types == ["text", "tool_use", "tool_use"]
        assert assistant["content"][1]["id"] == "c1"
        assert assistant["content"][1]["input"] == {"path": "a.py"}
        # BOTH results merged into ONE user message.
        results = turns[2]
        assert results["role"] == "user"
        assert [b["tool_use_id"] for b in results["content"]] == ["c1", "c2"]
        assert all(b["type"] == "tool_result" for b in results["content"])
        assert turns[3] == {"role": "assistant", "content": "Done."}

    def test_plain_history_unchanged_shape(self, turns_import):
        turns = self._func(turns_import)([
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ])
        assert turns == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]


# --- OpenAI-style (openrouter) -------------------------------------------------------
def _openai_chunk(content=None, tool_fragments=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_fragments)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _openai_fragment(index, id=None, name=None, arguments=None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


class TestOpenAIEventAssembly:
    def test_fragmented_tool_call(self):
        from seedcode.core.providers.openrouter import _iter_tool_stream

        chunks = [
            _openai_chunk(content="Checking."),
            _openai_chunk(tool_fragments=[
                _openai_fragment(0, id="call_1", name="read_file", arguments='{"pa')
            ]),
            _openai_chunk(tool_fragments=[
                _openai_fragment(0, arguments='th": "a.py"}')
            ]),
        ]
        events = list(_iter_tool_stream(iter(chunks)))
        assert events[0] == TextDelta("Checking.")
        call = events[1]
        assert call.id == "call_1" and call.name == "read_file"
        assert call.arguments == {"path": "a.py"} and not call.error

    def test_parallel_calls_by_index(self):
        from seedcode.core.providers.openrouter import _iter_tool_stream

        chunks = [
            _openai_chunk(tool_fragments=[
                _openai_fragment(0, id="a", name="list_dir", arguments="{}"),
                _openai_fragment(1, id="b", name="project_index", arguments="{}"),
            ]),
        ]
        events = list(_iter_tool_stream(iter(chunks)))
        assert [e.id for e in events] == ["a", "b"]

    def test_broken_json_carries_error(self):
        from seedcode.core.providers.openrouter import _iter_tool_stream

        chunks = [
            _openai_chunk(tool_fragments=[
                _openai_fragment(0, id="x", name="read_file", arguments='{"path"')
            ]),
        ]
        events = list(_iter_tool_stream(iter(chunks)))
        assert events[0].error and events[0].arguments == {}


class TestOpenAISerialization:
    def test_wire_shape(self):
        from seedcode.core.providers.openrouter import _to_api_tools

        wire = [_to_api_tools(m) for m in history_with_tools()]
        assistant = wire[2]
        assert assistant["role"] == "assistant"
        assert assistant["tool_calls"][0]["id"] == "c1"
        assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
        assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {
            "path": "a.py"
        }
        assert wire[3] == {"role": "tool", "tool_call_id": "c1", "content": "[OK] data"}
        assert wire[5] == {"role": "assistant", "content": "Done."}


# --- Responses API (freemodel codex) ----------------------------------------------------
class TestResponsesSerialization:
    def test_input_items(self):
        from seedcode.core.providers.freemodel import _to_responses_input

        items = _to_responses_input(history_with_tools())
        # assistant text, two function_calls, two outputs, final assistant
        assert items[0] == {"role": "user", "content": "do it"}
        assert items[1] == {"role": "assistant", "content": "Working."}
        assert items[2]["type"] == "function_call" and items[2]["call_id"] == "c1"
        assert json.loads(items[2]["arguments"]) == {"path": "a.py"}
        assert items[4] == {
            "type": "function_call_output", "call_id": "c1", "output": "[OK] data"
        }
        assert items[6] == {"role": "assistant", "content": "Done."}


# --- Ollama ------------------------------------------------------------------------------
class TestOllamaSerialization:
    def test_wire_shape(self):
        from seedcode.core.providers.ollama import _to_api_ollama_tools

        wire = [_to_api_ollama_tools(m) for m in history_with_tools()]
        assistant = wire[2]
        assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
        # Ollama takes arguments as a dict, not a JSON string.
        assert assistant["tool_calls"][0]["function"]["arguments"] == {"path": "a.py"}
        assert wire[3] == {"role": "tool", "content": "[OK] data"}


# --- default provider degrade -------------------------------------------------------------
class TestDefaultDegrade:
    def test_base_stream_chat_with_tools_yields_text(self):
        from dataclasses import dataclass

        from seedcode.core.providers.base import Provider, ToolSpec

        @dataclass
        class Plain(Provider):
            def __post_init__(self):
                self.id = "plain"
                self.label = "Plain"

            def validate_key(self, api_key):
                raise NotImplementedError

            def list_models(self, config):
                raise NotImplementedError

            def stream_chat(self, config, messages):
                yield "hello "
                yield "world"

        events = list(Plain().stream_chat_with_tools(None, [], [
            ToolSpec(name="t", description="d", parameters={})
        ]))
        assert events == [TextDelta("hello "), TextDelta("world")]
        assert Plain().supports_tools(None) is False
