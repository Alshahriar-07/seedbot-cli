"""Message model, memory, and command-registry tests: no network required."""

from __future__ import annotations

from seedcode.commands import _REGISTRY, is_command
from seedcode.core.models import Message
from seedcode.memory import list_sessions


def test_message_to_api() -> None:
    msg = Message(role="user", content="hi")
    assert msg.to_api() == {"role": "user", "content": "hi"}


def test_is_command() -> None:
    assert is_command("/help")
    assert not is_command("hello world")


def test_all_documented_commands_registered() -> None:
    for name in ("help", "model", "clear", "reset", "history", "config",
                 "about", "version", "exit"):
        assert name in _REGISTRY, f"missing command: {name}"


def test_list_sessions_returns_list() -> None:
    assert isinstance(list_sessions(), list)
