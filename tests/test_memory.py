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
    for name in ("help", "model", "provider", "apikey", "settings", "doctor",
                 "clear", "reset", "history", "config", "about", "version",
                 "exit"):
        assert name in _REGISTRY, f"missing command: {name}"


def test_list_sessions_returns_list() -> None:
    assert isinstance(list_sessions(), list)


def test_history_is_per_provider(tmp_path, monkeypatch) -> None:
    from seedcode.memory import HistoryStore
    from seedcode.utils import helpers

    monkeypatch.setattr(helpers, "app_dir", lambda: tmp_path)

    store_a = HistoryStore(sid="20260716-000001", provider_id="openrouter")
    store_b = HistoryStore(sid="20260716-000001", provider_id="ollama")
    assert store_a.path != store_b.path
    assert "openrouter" in str(store_a.path)

    store_a.save([Message(role="user", content="hi")])
    assert ("20260716-000001", 1) in list_sessions("openrouter")
    assert list_sessions("ollama") == []  # other providers see nothing


def test_drop_last_user_keeps_transcript_alternating() -> None:
    from seedcode.core.chat import ChatEngine
    from seedcode.core.models import AppConfig

    engine = ChatEngine(AppConfig())
    engine.add_user("hello")
    engine.drop_last_user()
    assert [m.role for m in engine.messages] == ["system"]
    # A completed exchange is never dropped.
    engine.add_user("hello")
    engine.add_assistant("hi")
    engine.drop_last_user()
    assert [m.role for m in engine.messages] == ["system", "user", "assistant"]
