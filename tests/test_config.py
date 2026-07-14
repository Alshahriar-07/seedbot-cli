"""Config model tests: no network, no API key required."""

from __future__ import annotations

from seedcode.core.models import AppConfig


def test_config_defaults() -> None:
    cfg = AppConfig()
    assert cfg.model == "z-ai/glm-5.2"
    assert cfg.provider == "OpenRouter"
    assert not cfg.is_configured()


def test_masked_key() -> None:
    assert AppConfig(api_key="").masked_key() == "(not set)"
    masked = AppConfig(api_key="sk-or-1234567890abcdef").masked_key()
    assert masked.startswith("sk-or-12") and masked.endswith("cdef")
    assert "..." in masked
