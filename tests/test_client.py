"""OpenRouter client/validation tests: no network required.

Empty and malformed keys are rejected before any HTTP request is made, so these
run offline.
"""

from __future__ import annotations

from seedcode.core.client import ValidationResult, validate_key


def test_validate_key_rejects_empty() -> None:
    result = validate_key("")
    assert isinstance(result, ValidationResult)
    assert not result.ok


def test_validate_key_rejects_bad_prefix() -> None:
    result = validate_key("not-an-openrouter-key")
    assert not result.ok
