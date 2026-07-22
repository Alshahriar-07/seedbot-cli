"""Element resolver: descriptions in, coordinates out.

This is the boundary that keeps coordinates away from the AI. Every semantic UI
action (``ui_click("Sign in button")``, ``ui_type("search box", ...)``) hands
the resolver a *description*; the resolver finds the matching on-screen element
and returns its clickable point. Resolution runs a deterministic ladder:

1. **Accessibility tree** (UI Automation) — the primary, exact source: fuzzy
   match the description against element role + name.
2. **OCR** — for windows that expose no automation tree (games, custom-drawn
   apps): locate the text on a screenshot and click its center.

The AI is never shown, and never supplies, the resulting coordinates. If
nothing resolves, a :class:`ResolveError` flows back so the dispatcher's
recovery engine can retry (refocus, re-snapshot) or, as a last resort, ask the
AI to replan against a fresh semantic snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ui.fuzzy import fuzzy_match

# A fuzzy score below this means "no confident match" — better to fail and let
# recovery re-snapshot than to click the wrong thing.
_MIN_SCORE = 200.0

# Role words the AI naturally appends to a description ("Save button", "search
# box"); stripped before matching so they don't fight the element's own role.
_ROLE_HINTS = {
    "button": "button",
    "btn": "button",
    "input": "input",
    "field": "input",
    "box": "input",
    "textbox": "input",
    "link": "link",
    "menu": "menu",
    "menuitem": "menuitem",
    "item": "listitem",
    "tab": "tab",
    "checkbox": "checkbox",
    "check": "checkbox",
    "radio": "radio",
    "combobox": "combobox",
    "dropdown": "combobox",
    "icon": "button",
}


class ResolveError(Exception):
    """A described element could not be located on screen."""


@dataclass(slots=True)
class ResolvedElement:
    """An element the resolver located, with the point to act on."""

    x: int
    y: int
    role: str
    name: str
    score: float
    source: str  # "accessibility" or "ocr"

    def describe(self) -> str:
        return f'{self.role} "{self.name or "(unnamed)"}" via {self.source}'


class ElementResolver:
    """Turns element descriptions into concrete screen points.

    Deterministic and offline. Drivers are injectable so the resolution logic
    can be unit-tested without a live desktop.
    """

    def __init__(self, vision: Any = None, screen: Any = None) -> None:
        if vision is None:
            from . import vision as vision  # type: ignore
        if screen is None:
            from . import screen as screen  # type: ignore
        self._vision = vision
        self._screen = screen

    def resolve(self, description: str, window_title: str | None = None) -> ResolvedElement:
        """Locate the element matching ``description`` and return its point."""
        desc = (description or "").strip()
        if not desc:
            raise ResolveError("No element description was given.")

        # 1) Accessibility tree — the exact, preferred path.
        try:
            _title, elements = self._vision.snapshot(window_title)
        except Exception:
            elements = []
        hit = self._match_elements(desc, elements)
        if hit is not None:
            return hit

        # 2) OCR fallback — only for windows with no usable automation tree.
        ocr_hit = self._match_ocr(desc, window_title)
        if ocr_hit is not None:
            return ocr_hit

        raise ResolveError(
            f'Could not find "{desc}" on screen. '
            "Take a fresh computer_see snapshot and describe a visible element."
        )

    # --- accessibility matching ---------------------------------------------
    def _match_elements(self, desc: str, elements: list) -> ResolvedElement | None:
        if not elements:
            return None
        query, wanted_role = self._split_role_hint(desc)
        best: ResolvedElement | None = None
        for el in elements:
            # Score the query against the element name (primary) and, more
            # weakly, its role, so "search box" still finds an unnamed input.
            name_score = fuzzy_match(query, el.name).score if query else 0.0
            role_score = 0.0
            if wanted_role and el.role == wanted_role:
                role_score = 150.0
            elif wanted_role and el.role != wanted_role:
                role_score = -60.0  # penalise a role mismatch, don't exclude
            score = name_score + role_score
            # An unnamed element that matches only by role still counts when
            # the description was essentially just a role ("the input").
            if not query and wanted_role and el.role == wanted_role:
                score = _MIN_SCORE + 1.0
            if not getattr(el, "enabled", True):
                score -= 80.0
            if best is None or score > best.score:
                best = ResolvedElement(
                    x=el.x, y=el.y, role=el.role, name=el.name,
                    score=score, source="accessibility",
                )
        if best is not None and best.score >= _MIN_SCORE:
            return best
        return None

    def _split_role_hint(self, desc: str) -> tuple[str, str | None]:
        """Peel a trailing role word off the description, if present."""
        words = desc.split()
        if len(words) >= 2:
            role = _ROLE_HINTS.get(words[-1].lower())
            if role is not None:
                return " ".join(words[:-1]).strip(), role
        # A one-word role-only description ("button") still carries the hint.
        if len(words) == 1:
            role = _ROLE_HINTS.get(words[0].lower())
            if role is not None:
                return "", role
        return desc, None

    # --- OCR fallback --------------------------------------------------------
    def _match_ocr(self, desc: str, window_title: str | None) -> ResolvedElement | None:
        """Find text on a screenshot and return its center point."""
        locate = getattr(self._vision, "ocr_locate", None)
        if locate is None or not self._vision.ocr_available():
            return None
        try:
            path = self._screen.capture()
            box = locate(path, desc)  # (left, top, width, height) or None
        except Exception:
            return None
        if not box:
            return None
        left, top, width, height = box
        return ResolvedElement(
            x=int(left + width // 2), y=int(top + height // 2),
            role="text", name=desc, score=_MIN_SCORE, source="ocr",
        )
