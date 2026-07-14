"""Low-level response streaming.

Iterates an OpenAI/OpenRouter streaming completion and yields text pieces. Error
translation is handled one layer up in :mod:`seedcode.core.chat` so this stays a
pure, reusable generator.
"""

from __future__ import annotations

from collections.abc import Iterator


def iter_stream(stream) -> Iterator[str]:
    """Yield non-empty content deltas from a streaming chat completion."""
    for event in stream:
        if not event.choices:
            continue
        delta = event.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece
