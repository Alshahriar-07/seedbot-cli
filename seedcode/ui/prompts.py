"""Compatibility shim — the input component moved to :mod:`seedcode.ui.textbox`.

Kept so existing imports (``from ..ui.prompts import read_line``) continue
to work; new code should import from ``textbox`` directly.
"""

from __future__ import annotations

from .textbox import prompt_label, read_line, read_text
from .theme import pt_style

# Legacy name: a static style object matching the current theme at import
# time. Prefer pt_style() for live-theme correctness.
PT_STYLE = pt_style()

__all__ = ["PT_STYLE", "prompt_label", "read_line", "read_text", "pt_style"]
