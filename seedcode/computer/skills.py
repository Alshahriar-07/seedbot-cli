"""Skill engine: high-level, deterministic procedures the AI selects by name.

A *skill* is Seed Code's unit of knowledge — "launch an app", "search
YouTube", "create a Python project". The AI planner chooses a skill and
supplies parameters; the skill expands into a fixed sequence of deterministic
Computer Engine operations. The AI never sees those inner steps and never
produces coordinates, keystrokes, or click sequences.

Each skill declares:

* ``name`` / ``summary`` / ``params`` — its catalog entry (what the AI reads).
* ``level`` — the :class:`PermissionLevel` required to run it.
* ``run(ctx, params) -> Outcome`` — the deterministic body, given a
  :class:`SkillContext` that exposes the controller, element resolver, state
  manager and permission manager.

Skills raise :class:`SkillError` on unrecoverable failure; they return an
:class:`Outcome` carrying the expectation the dispatcher will verify. Skills
contain no AI calls and work offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..tools.permissions import PermissionLevel


class SkillError(Exception):
    """A skill could not complete (after its own inline handling)."""


@dataclass(slots=True)
class Outcome:
    """What a skill produced, plus how to verify it succeeded."""

    detail: str
    expected: dict[str, Any] | None = None
    # Hints the dispatcher passes to recovery if verification fails.
    window_title: str | None = None
    app_target: str | None = None


@dataclass
class SkillContext:
    """Everything a skill body may use — all deterministic, no AI."""

    controller: Any            # ComputerController: mouse/keyboard/windows/...
    resolver: Any              # ElementResolver: description -> point
    state: Any                 # StateManager: engine memory
    permissions: Any           # PermissionManager: require()/confirm_action()

    def click_described(self, description: str, *, button: str = "left", double: bool = False) -> str:
        """Resolve a described element and click it — the resolver owns coords."""
        hit = self.resolver.resolve(description)
        self.controller.mouse_click(hit.x, hit.y, button, double)
        self.state.record_action(f"clicked {description}")
        return f"clicked {hit.describe()}"

    def type_into(self, description: str, text: str, *, secret: bool = False) -> str:
        """Focus a described field, then type into it."""
        hit = self.resolver.resolve(description)
        self.controller.mouse_click(hit.x, hit.y)
        self.controller.type_text(text)
        self.state.record_action(f"typed into {description}")
        shown = "•" * len(text) if secret else text
        return f"typed '{shown}' into {hit.describe()}"


# A skill body: (ctx, params) -> Outcome.
SkillBody = Callable[[SkillContext, dict[str, Any]], Outcome]


@dataclass(slots=True)
class Skill:
    """A named, permissioned, deterministic procedure."""

    name: str
    summary: str
    level: PermissionLevel
    body: SkillBody
    params: dict[str, str] = field(default_factory=dict)
    sensitive: bool = False  # requires per-action confirmation even if level ok

    def run(self, ctx: SkillContext, params: dict[str, Any]) -> Outcome:
        # Enforce the skill's permission floor before doing anything.
        ctx.permissions.require(self.level, f"skill '{self.name}'")
        return self.body(ctx, params or {})


class SkillRegistry:
    """The catalog of known skills, keyed by name."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        self._skills[skill.name] = skill
        return skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(str(name).strip().lower())

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def manifest(self, max_level: PermissionLevel | None = None) -> str:
        """Human/AI-readable catalog, optionally hiding skills above a level."""
        lines = []
        for skill in self.all():
            if max_level is not None and skill.level > max_level:
                continue
            args = ", ".join(skill.params) if skill.params else "no params"
            lines.append(f"- {skill.name}({args}) — {skill.summary}")
        return "\n".join(lines)


# Module-level catalog populated by ``catalog.py`` at import time.
REGISTRY = SkillRegistry()


def skill(name, summary, level, params=None, sensitive=False):
    """Decorator: register a function as a skill body."""

    def deco(fn: SkillBody) -> SkillBody:
        REGISTRY.register(
            Skill(
                name=name.strip().lower(),
                summary=summary,
                level=level,
                body=fn,
                params=params or {},
                sensitive=sensitive,
            )
        )
        return fn

    return deco
