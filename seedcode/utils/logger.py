"""Minimal logging helper for Seed Code.

Seed Code is a quiet CLI: by default logging is a no-op (a ``NullHandler``) so
nothing leaks into the user's terminal. Centralising logger creation here means
any future diagnostics attach in one place without touching call sites.
"""

from __future__ import annotations

import logging

_ROOT = "seedcode"
_configured = False


def get_logger(name: str = _ROOT) -> logging.Logger:
    """Return a namespaced logger that stays silent unless a handler is added."""
    global _configured
    if not _configured:
        logging.getLogger(_ROOT).addHandler(logging.NullHandler())
        _configured = True
    return logging.getLogger(name)
