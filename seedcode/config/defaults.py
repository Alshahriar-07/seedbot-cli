"""Configuration defaults and environment overrides.

Kept import-light (no project imports) so it can be referenced from anywhere
without risk of an import cycle.
"""

from __future__ import annotations

# Environment variable that always overrides the stored API key (CI / power users).
ENV_KEY = "OPENROUTER_API_KEY"

# Filename of the JSON config document within the per-user app directory.
CONFIG_FILENAME = "config.json"
