"""Config model tests: no network, no API key required."""

from __future__ import annotations

from seedcode.core.models import DEFAULT_MAX_TOKENS, AppConfig

_ALL = ("openrouter", "freemodel_claude", "freemodel_codex", "aerolink", "ollama")


def test_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.model == ""  # models are never hardcoded
    assert cfg.provider == "freemodel_claude"
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS
    assert not cfg.is_configured()


def test_max_tokens_clamped() -> None:
    cfg = AppConfig(model="some/model", max_tokens=65536)
    assert cfg.effective_max_tokens() == 4096  # never send huge budgets
    cfg.max_tokens = 0
    assert cfg.effective_max_tokens() == 1
    cfg.max_tokens = 2048
    assert cfg.effective_max_tokens() == 2048


def test_free_models_capped_at_default() -> None:
    cfg = AppConfig(model="meta-llama/llama-3-8b:free", max_tokens=4096)
    assert cfg.effective_max_tokens() == DEFAULT_MAX_TOKENS


def test_agent_mode_raises_token_ceiling() -> None:
    from seedcode.core.models import AGENT_MAX_TOKENS

    cfg = AppConfig(model="some/model", agent_mode=True)
    # The untouched default budget upgrades so agent turns can emit files.
    assert cfg.effective_max_tokens() == AGENT_MAX_TOKENS
    # An explicit user budget is respected (clamped to the agent ceiling).
    cfg.max_tokens = 2048
    assert cfg.effective_max_tokens() == 2048
    cfg.max_tokens = 65536
    assert cfg.effective_max_tokens() == AGENT_MAX_TOKENS
    # Free models stay capped even in agent mode.
    cfg.max_tokens = DEFAULT_MAX_TOKENS
    cfg.model = "meta-llama/llama-3-8b:free"
    assert cfg.effective_max_tokens() == DEFAULT_MAX_TOKENS


def test_tool_message_round_trip() -> None:
    from seedcode.core.models import Message, ToolCallRecord

    original = Message(
        role="assistant",
        content="Working.",
        tool_calls=[ToolCallRecord(id="c1", name="read_file", arguments={"path": "a"})],
    )
    restored = Message.model_validate(original.model_dump())
    assert restored.tool_calls[0].id == "c1"
    assert restored.tool_calls[0].arguments == {"path": "a"}

    result = Message(role="tool", content="[OK]", tool_call_id="c1", tool_name="read_file")
    restored = Message.model_validate(result.model_dump())
    assert restored.role == "tool" and restored.tool_call_id == "c1"

    # Old persisted histories (no tool fields) still load.
    legacy = Message.model_validate({"role": "user", "content": "hi"})
    assert legacy.tool_calls == [] and legacy.tool_call_id == ""


def test_per_provider_keys() -> None:
    cfg = AppConfig()
    cfg.set_api_key("freemodel_claude", "fe_oa_abc")
    cfg.set_api_key("aerolink", "al-key")
    assert cfg.get_api_key("freemodel_claude") == "fe_oa_abc"
    assert cfg.get_api_key() == "fe_oa_abc"  # active provider default
    cfg.provider = "aerolink"
    assert cfg.get_api_key() == "al-key"


def test_is_configured_per_provider() -> None:
    cfg = AppConfig(model="some/model")
    assert not cfg.is_configured()  # freemodel_claude without key
    cfg.set_api_key("freemodel_claude", "fe_oa_abc")
    assert cfg.is_configured()
    cfg = AppConfig(provider="ollama", model="llama3.2")
    assert cfg.is_configured()  # ollama never needs a key


def test_model_memory_per_provider() -> None:
    cfg = AppConfig(model="a/b")
    cfg.provider = "ollama"
    assert cfg.recall_model() == ""
    cfg.model = "llama3.2"
    cfg.provider = "freemodel_claude"
    assert cfg.recall_model() == "a/b"


def test_legacy_config_migrates() -> None:
    # v0.x flat key + display-name provider (OpenRouter was the original
    # backend, and is a first-class provider again).
    cfg = AppConfig.model_validate(
        {"api_key": "sk-or-old", "provider": "OpenRouter", "model": "x/y"}
    )
    assert cfg.provider == "openrouter"
    assert cfg.get_api_key("openrouter") == "sk-or-old"
    assert cfg.providers["openrouter"].model == "x/y"


def test_v1_config_migrates_to_nested_providers() -> None:
    cfg = AppConfig.model_validate(
        {
            "provider": "aerolink",
            "model": "claude-x",
            "api_keys": {"openrouter": "sk-or-abc", "aerolink": "al-key"},
            "models": {"openrouter": "a/b"},
        }
    )
    assert cfg.active_provider == "aerolink"
    assert cfg.providers["aerolink"].model == "claude-x"
    assert cfg.providers["aerolink"].api_key == "al-key"
    assert cfg.providers["openrouter"].model == "a/b"
    assert cfg.providers["openrouter"].api_key == "sk-or-abc"


def test_v2_single_freemodel_splits_into_two_providers() -> None:
    # v2.x: one "freemodel" entry with claude/codex sub-backends becomes
    # the two first-class providers; the shared key goes to both.
    cfg = AppConfig.model_validate(
        {
            "active_provider": "freemodel",
            "providers": {
                "freemodel": {
                    "api_key": "fe_oa_shared",
                    "model": "claude-live",
                    "options": {"backend": "claude", "model_codex": "gpt-x"},
                },
            },
        }
    )
    assert cfg.active_provider == "freemodel_claude"  # backend claude was active
    assert cfg.get_api_key("freemodel_claude") == "fe_oa_shared"
    assert cfg.get_api_key("freemodel_codex") == "fe_oa_shared"
    assert cfg.providers["freemodel_claude"].model == "claude-live"
    assert cfg.providers["freemodel_codex"].model == "gpt-x"
    assert "freemodel" not in cfg.providers


def test_v2_freemodel_default_backend_maps_to_codex() -> None:
    cfg = AppConfig.model_validate(
        {
            "active_provider": "freemodel",
            "providers": {"freemodel": {"api_key": "fe_oa_k", "model": "gpt-4o"}},
        }
    )
    assert cfg.active_provider == "freemodel_codex"  # codex was the default
    assert cfg.providers["freemodel_codex"].model == "gpt-4o"
    assert cfg.get_api_key("freemodel_claude") == "fe_oa_k"


def test_unknown_active_provider_falls_back_to_default() -> None:
    cfg = AppConfig.model_validate({"active_provider": "bogus"})
    assert cfg.active_provider == "freemodel_claude"


def test_stored_shape_is_nested() -> None:
    dumped = AppConfig().model_dump()
    assert dumped["active_provider"] == "freemodel_claude"
    assert set(dumped["providers"]) >= set(_ALL)
    assert dumped["providers"]["freemodel_claude"] == {
        "api_key": "", "model": "", "options": {}
    }
    # Round-trips losslessly.
    cfg = AppConfig(model="a/b")
    cfg.set_api_key("aerolink", "al-key")
    cfg.provider_options("openrouter")["mode"] = "pro"
    assert AppConfig.model_validate(cfg.model_dump()) == cfg


def test_five_provider_keys_are_isolated() -> None:
    cfg = AppConfig()
    cfg.set_api_key("openrouter", "sk-or-1")
    cfg.set_api_key("freemodel_claude", "fe_oa_2")
    cfg.set_api_key("freemodel_codex", "fe_oa_3")
    cfg.set_api_key("aerolink", "al-4")
    assert cfg.get_api_key("openrouter") == "sk-or-1"
    assert cfg.get_api_key("freemodel_claude") == "fe_oa_2"
    assert cfg.get_api_key("freemodel_codex") == "fe_oa_3"
    assert cfg.get_api_key("aerolink") == "al-4"
    assert cfg.get_api_key("ollama") == ""


def test_switching_never_overwrites_other_providers() -> None:
    cfg = AppConfig(model="claude-one")
    cfg.set_api_key("freemodel_claude", "fe_oa_abc")
    cfg.provider = "freemodel_codex"
    cfg.set_api_key("freemodel_codex", "fe_oa_xyz")
    cfg.model = "gpt-x"
    cfg.provider = "ollama"
    cfg.model = "llama3.2"
    # Every provider kept its own key and model.
    assert cfg.providers["freemodel_claude"].api_key == "fe_oa_abc"
    assert cfg.providers["freemodel_claude"].model == "claude-one"
    assert cfg.providers["freemodel_codex"].api_key == "fe_oa_xyz"
    assert cfg.providers["freemodel_codex"].model == "gpt-x"
    assert cfg.providers["ollama"].model == "llama3.2"
    # And switching back restores instantly.
    cfg.provider = "freemodel_claude"
    assert cfg.model == "claude-one"
    assert cfg.get_api_key() == "fe_oa_abc"


def test_masked_key() -> None:
    assert AppConfig().masked_key() == "(not set)"
    cfg = AppConfig()
    cfg.set_api_key("freemodel_claude", "fe_oa_1234567890abcdef")
    masked = cfg.masked_key("freemodel_claude")
    assert masked.startswith("fe_oa_12") and masked.endswith("cdef")
    assert "..." in masked
