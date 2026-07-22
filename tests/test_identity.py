"""Tests for the Seed Code identity layer."""

from __future__ import annotations

import pytest

from seedcode.core.identity import build_system_prompt
from seedcode.core.chat import ChatEngine
from seedcode.core.models import AppConfig


def test_build_system_prompt_includes_seed_code_identity():
    """The system prompt must always start with Seed Code identity."""
    prompt = build_system_prompt("OpenRouter", "gpt-4")
    assert "You are Seed Code" in prompt
    assert "created by al shahriar sowan" in prompt.lower()


def test_build_system_prompt_includes_reasoning_engine():
    """The prompt must mention the current reasoning engine."""
    prompt = build_system_prompt("FreeModel Claude", "claude-opus-4-8")
    assert "claude-opus-4-8" in prompt
    assert "FreeModel Claude" in prompt


def test_build_system_prompt_distinguishes_application_from_engine():
    """The prompt must clarify Seed Code vs. the underlying model."""
    prompt = build_system_prompt("OpenRouter", "gpt-5.5")
    # Must include guidance on how to answer identity questions
    assert "reasoning engine" in prompt.lower()
    assert "not chatgpt" in prompt.lower() or "not the underlying" in prompt.lower()


def test_build_system_prompt_has_identity_qa_guidance():
    """The prompt must include examples for identity questions."""
    prompt = build_system_prompt("AeroLink", "claude-sonnet-5")
    # Should contain guidance for common identity questions
    assert "who created you" in prompt.lower() or "who made you" in prompt.lower()
    assert "al shahriar sowan" in prompt.lower()


def test_chat_engine_uses_identity_prompt():
    """ChatEngine must initialize with an identity-aware system prompt."""
    config = AppConfig()
    config.provider = "freemodel_claude"
    config.model = "claude-opus-4-8"
    engine = ChatEngine(config)

    # First message should be the system prompt
    assert len(engine.messages) == 1
    assert engine.messages[0].role == "system"

    system_content = engine.messages[0].content
    assert "Seed Code" in system_content
    assert "Al Shahriar Sowan" in system_content
    assert "claude-opus-4-8" in system_content


def test_chat_engine_different_providers_get_identity():
    """All providers should receive Seed Code identity via ChatEngine."""
    providers = [
        ("openrouter", "gpt-4-turbo"),
        ("freemodel_claude", "claude-sonnet-5"),
        ("freemodel_codex", "gpt-5.5"),
        ("aerolink", "claude-opus-4-7"),
        ("ollama", "llama3.2"),
    ]

    for provider_id, model in providers:
        config = AppConfig()
        config.provider = provider_id
        config.model = model
        engine = ChatEngine(config)

        system_content = engine.messages[0].content
        assert "Seed Code" in system_content, f"{provider_id} missing Seed Code identity"
        assert "Al Shahriar Sowan" in system_content, f"{provider_id} missing creator"
        assert model in system_content, f"{provider_id} missing model info"


def test_identity_prompt_preserves_task_instructions():
    """The prompt must include task/coding instructions after identity."""
    prompt = build_system_prompt("OpenRouter", "gpt-4")
    # Should have coding-related instructions
    assert "code" in prompt.lower()
    assert "markdown" in prompt.lower() or "fenced" in prompt.lower()


def test_identity_single_source_of_truth():
    """Changing identity should require editing only identity.py."""
    # This test verifies the architecture: providers don't contain identity strings
    from seedcode.core.providers import openrouter, aerolink, ollama, freemodel

    # Check that provider modules don't hardcode "Seed Code" identity
    for module in [openrouter, aerolink, ollama, freemodel]:
        source = module.__file__
        if source:
            with open(source, encoding="utf-8") as f:
                content = f.read()
                # Should NOT contain identity strings (only import/reference)
                assert "created by Al Shahriar Sowan" not in content, \
                    f"{module.__name__} contains hardcoded identity"
                # May reference build_system_prompt but shouldn't duplicate identity
                if "You are Seed Code" in content and "build_system_prompt" not in content:
                    pytest.fail(f"{module.__name__} has duplicate identity string")
