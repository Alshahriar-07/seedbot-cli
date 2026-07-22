"""Fuzzy matching for the interactive components.

Subsequence matching with a smallest-window score, tuned for picking model
ids and command names:

* ``cld`` matches **Cl**au**d**e
* ``gpt55`` matches **GPT-5.5** (separators are skipped freely)
* ``opus`` matches Claude **Opus**

Scoring prefers, in order: exact substring at a word start, exact substring
anywhere, then the tightest subsequence window with bonuses for matches at
word boundaries and consecutive runs. Pure Python, no dependencies, fast
enough for thousand-entry model lists (a single linear scan per candidate).
"""

from __future__ import annotations

from dataclasses import dataclass

_WORD_SEPARATORS = set(" -_./:@")


@dataclass(slots=True)
class FuzzyResult:
    """Outcome of matching one query against one candidate string."""

    matched: bool
    score: float
    positions: tuple[int, ...]  # candidate indices to highlight


_NO_MATCH = FuzzyResult(False, float("-inf"), ())


def _is_boundary(text: str, i: int) -> bool:
    """True when ``text[i]`` starts a word (position 0, after a separator,
    a digit after a letter, or an upper-case letter after a lower-case one)."""
    if i == 0:
        return True
    prev, ch = text[i - 1], text[i]
    if prev in _WORD_SEPARATORS:
        return True
    if ch.isdigit() and prev.isalpha():
        return True
    if ch.isupper() and prev.islower():
        return True
    return False


def _subsequence_from(low_text: str, low_query: str, start: int) -> list[int] | None:
    """Greedy left-to-right subsequence match beginning at/after ``start``."""
    positions: list[int] = []
    i = start
    for qc in low_query:
        j = low_text.find(qc, i)
        if j < 0:
            return None
        positions.append(j)
        i = j + 1
    return positions


def fuzzy_match(query: str, text: str) -> FuzzyResult:
    """Match ``query`` against ``text``; empty queries match everything."""
    if not query:
        return FuzzyResult(True, 0.0, ())
    if not text:
        return _NO_MATCH

    low_text = text.lower()
    low_query = "".join(ch for ch in query.lower() if not ch.isspace())
    if not low_query:
        return FuzzyResult(True, 0.0, ())

    # Fast paths: exact substring (best at a word boundary).
    idx = low_text.find(low_query)
    if idx >= 0:
        span = tuple(range(idx, idx + len(low_query)))
        bonus = 200.0 if _is_boundary(text, idx) else 100.0
        return FuzzyResult(True, 1000.0 + bonus - idx * 0.5 - len(text) * 0.01, span)

    # Subsequence: try anchoring at each occurrence of the first query char
    # and keep the best-scoring window (bounded to a handful of anchors).
    first = low_query[0]
    best: FuzzyResult = _NO_MATCH
    anchor = low_text.find(first)
    tries = 0
    while anchor >= 0 and tries < 8:
        positions = _subsequence_from(low_text, low_query, anchor)
        if positions is None:
            break  # later anchors can only fail too
        score = _score(text, positions)
        if score > best.score:
            best = FuzzyResult(True, score, tuple(positions))
        anchor = low_text.find(first, anchor + 1)
        tries += 1
    return best


def _score(text: str, positions: list[int]) -> float:
    window = positions[-1] - positions[0] + 1
    score = 500.0 - (window - len(positions)) * 10.0  # tighter window is better
    for k, pos in enumerate(positions):
        if _is_boundary(text, pos):
            score += 15.0
        if k > 0 and positions[k - 1] == pos - 1:
            score += 5.0  # consecutive run
    score -= positions[0] * 0.5  # earlier start is better
    score -= len(text) * 0.01  # shorter candidates win ties
    return score


def fuzzy_filter(
    query: str, items: list, key=lambda item: str(item)
) -> list[tuple[object, FuzzyResult]]:
    """Return ``(item, result)`` for matching items, best score first.

    Sorting is stable for equal scores, so the caller's original order is
    preserved within ties (important for grouped model lists).
    """
    scored: list[tuple[object, FuzzyResult]] = []
    for item in items:
        result = fuzzy_match(query, key(item))
        if result.matched:
            scored.append((item, result))
    if query:
        scored.sort(key=lambda pair: -pair[1].score)
    return scored
