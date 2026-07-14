"""Configuration loading and saving for Seed Code.

The config is a single JSON document under ``~/.seedcode/config.json``. Loading
is fault-tolerant: a missing or corrupt file yields sane defaults rather than a
crash, honouring the rule "never crash".
"""

from __future__ import annotations

import json
import os

from ..core.models import AppConfig
from ..utils.helpers import config_path, restrict_permissions
from .defaults import ENV_KEY


def load_config() -> AppConfig:
    """Load configuration from disk, falling back to defaults on any error."""
    path = config_path()
    config = AppConfig()

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            config = AppConfig.model_validate(raw)
        except (json.JSONDecodeError, ValueError, OSError):
            # Corrupt or unreadable config -> start from defaults instead of dying.
            config = AppConfig()

    # An explicit environment variable always wins for the API key.
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_key:
        config.api_key = env_key

    return config


def save_config(config: AppConfig) -> None:
    """Persist configuration to disk with owner-only permissions."""
    path = config_path()
    path.write_text(
        json.dumps(config.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    restrict_permissions(path)
