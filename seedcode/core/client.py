"""OpenRouter connectivity: SDK client construction and API-key validation.

OpenRouter is OpenAI-API compatible, so the official OpenAI SDK is reused with
``base_url`` pointed at OpenRouter. Key validation is a lightweight authenticated
GET that only inspects the status code, so the response body is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from openai import OpenAI

from .models import AppConfig

_BASE_URL = "https://openrouter.ai/api/v1"
# Sent so Seed Code shows up correctly in OpenRouter dashboards / rankings.
_HEADERS = {
    "HTTP-Referer": "https://github.com/Alshahriar-07/seedbot-cli",
    "X-Title": "Seed Code",
}
_VALIDATE_URL = "https://openrouter.ai/api/v1/key"
_TIMEOUT = 15.0


def build_client(config: AppConfig) -> OpenAI:
    """Create an OpenAI SDK client pointed at OpenRouter."""
    return OpenAI(
        api_key=config.api_key,
        base_url=_BASE_URL,
        default_headers=_HEADERS,
    )


@dataclass(slots=True)
class ValidationResult:
    """Outcome of an API key validation attempt."""

    ok: bool
    message: str


def validate_key(api_key: str) -> ValidationResult:
    """Check whether ``api_key`` is accepted by OpenRouter.

    Returns a :class:`ValidationResult` instead of raising so callers can render
    a friendly message. Network failures are reported as recoverable, not fatal.
    """
    key = api_key.strip()
    if not key:
        return ValidationResult(False, "API key is empty.")
    if not key.startswith("sk-or-"):
        # OpenRouter keys are prefixed sk-or-... — catch obvious typos early.
        return ValidationResult(
            False, "That does not look like an OpenRouter key (expected 'sk-or-...')."
        )

    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = httpx.get(_VALIDATE_URL, headers=headers, timeout=_TIMEOUT)
    except httpx.TimeoutException:
        return ValidationResult(False, "Validation timed out. Check your connection.")
    except httpx.HTTPError:
        return ValidationResult(False, "Could not reach OpenRouter. Check your connection.")

    if response.status_code == 200:
        return ValidationResult(True, "API key verified.")
    if response.status_code in (401, 403):
        return ValidationResult(False, "API key was rejected by OpenRouter.")
    return ValidationResult(
        False, f"Unexpected response from OpenRouter (HTTP {response.status_code})."
    )
