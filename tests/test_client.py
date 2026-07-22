"""Provider registry and validation tests: no network required.

Empty and malformed keys are rejected before any HTTP request is made, so these
run offline.
"""

from __future__ import annotations

from seedcode.core.providers import PROVIDERS, ProviderError, get_provider
from seedcode.core.providers.base import ValidationResult
from seedcode.core.providers.freemodel import (
    AUTO_MODEL,
    CLAUDE_BASE,
    CLAUDE_FALLBACK_MODELS,
    CODEX_BASE,
)


def test_registry_has_exactly_five_providers() -> None:
    assert set(PROVIDERS) == {
        "openrouter",
        "freemodel_claude",
        "freemodel_codex",
        "aerolink",
        "ollama",
    }


def test_provider_menu_order() -> None:
    # Insertion order IS the /provider menu order.
    assert list(PROVIDERS) == [
        "openrouter",
        "freemodel_claude",
        "freemodel_codex",
        "aerolink",
        "ollama",
    ]


def test_providers_are_fully_independent() -> None:
    # Distinct instances, own identity, own session status slot.
    instances = list(PROVIDERS.values())
    assert len({id(p) for p in instances}) == len(instances)
    assert all(p.status == "Not Checked" for p in instances)


def test_get_provider_is_case_insensitive() -> None:
    assert get_provider("OpenRouter").id == "openrouter"
    assert get_provider("FreeModel_Claude").id == "freemodel_claude"
    assert get_provider("FREEMODEL_CODEX").id == "freemodel_codex"
    assert get_provider("OLLAMA").id == "ollama"


def test_get_provider_rejects_unknown() -> None:
    try:
        get_provider("nope")
    except ProviderError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ProviderError")


def test_key_providers_reject_empty_key_offline() -> None:
    # Empty = missing key (no request possible); anything else requires a
    # REAL API request — no offline heuristics, so nothing else is testable
    # without network.
    for pid in ("openrouter", "freemodel_claude", "freemodel_codex", "aerolink"):
        result = PROVIDERS[pid].validate_key("")
        assert isinstance(result, ValidationResult)
        assert not result.ok


def test_freemodel_auto_sentinel() -> None:
    assert AUTO_MODEL == "auto"
    assert PROVIDERS["freemodel_claude"].supports_auto
    assert PROVIDERS["freemodel_codex"].supports_auto


def test_freemodel_claude_identity() -> None:
    provider = PROVIDERS["freemodel_claude"]
    assert provider.label == "FreeModel Claude"
    assert provider.base_url == CLAUDE_BASE == "https://cc.freemodel.dev"
    assert provider.backend_label == "Claude API"
    assert provider.requires_key


def test_freemodel_codex_identity() -> None:
    provider = PROVIDERS["freemodel_codex"]
    assert provider.label == "FreeModel Codex"
    assert provider.base_url == CODEX_BASE == "https://api.freemodel.dev"
    assert provider.backend_label == "Responses API"
    assert provider.requires_key


def test_freemodel_claude_fallback_list_is_claude_only() -> None:
    assert CLAUDE_FALLBACK_MODELS  # never empty: Claude models stay selectable
    assert all(mid.startswith("claude-") for mid, _ in CLAUDE_FALLBACK_MODELS)


def test_freemodel_claude_falls_back_offline(monkeypatch) -> None:
    # Discovery failing must yield the maintained fallback list, not an error.
    from seedcode.core.models import AppConfig

    provider = PROVIDERS["freemodel_claude"]

    def boom(api_key: str):
        raise ProviderError("catalogue down")

    monkeypatch.setattr(provider, "_fetch", boom)
    models = provider.list_models(AppConfig())
    assert [m.id for m in models] == [mid for mid, _ in CLAUDE_FALLBACK_MODELS]


def test_no_provider_shares_another_providers_model_list() -> None:
    # Each provider's list_models is its own bound method on its own class —
    # never a shared or borrowed implementation.
    impls = {
        pid: p.list_models.__func__  # type: ignore[attr-defined]
        for pid, p in PROVIDERS.items()
    }
    assert len(set(impls.values())) == len(impls)


def test_openrouter_mode_setting_offline() -> None:
    from seedcode.core.models import AppConfig

    cfg = AppConfig()
    provider = PROVIDERS["openrouter"]
    assert provider.mode(cfg) == "free"  # safe default
    ok, _ = provider.set_extra_setting(cfg, "mode", "pro")
    assert ok and provider.mode(cfg) == "pro"
    ok, _ = provider.set_extra_setting(cfg, "mode", "nonsense")
    assert not ok and provider.mode(cfg) == "pro"  # unchanged on bad input


def test_aerolink_rejects_empty_key_offline() -> None:
    assert not PROVIDERS["aerolink"].validate_key("").ok


def test_ollama_needs_no_key() -> None:
    provider = PROVIDERS["ollama"]
    assert not provider.requires_key
    assert provider.validate_key("").ok
