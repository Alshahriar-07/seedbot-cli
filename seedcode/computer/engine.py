"""Computer Engine facade: the stable, offline, AI-independent entry point.

This is the single object the rest of Seed Code talks to. It owns and wires the
deterministic subsystems — controller (drivers), element resolver, state
manager, verification engine, recovery engine and the skill dispatcher — and
exposes a small, stable API:

* :meth:`run_skill`  — run a named skill (or ``ui_*`` semantic verb) end-to-end
  with verification and recovery; returns a :class:`DispatchResult`.
* :meth:`state`      — the current :class:`ComputerState` (engine memory).
* :meth:`see`        — a semantic snapshot for the AI to replan against.
* :meth:`catalog`    — the skill manifest text for the AI, filtered by level.

The engine contains no provider/AI code and works offline. It is created once
per session (lazily) and holds no per-request state beyond the shared
StateManager.
"""

from __future__ import annotations

from typing import Any

from ..tools.permissions import PermissionLevel
from . import catalog as _catalog  # noqa: F401 — import populates the skill registry
from .dispatcher import DispatchResult, SkillDispatcher
from .recovery import RecoveryEngine
from .resolver import ElementResolver
from .skills import REGISTRY
from .state import ComputerState, StateManager
from .verifier import VerificationEngine


class ComputerEngine:
    """The deterministic hands, eyes, memory and reflexes of Seed Code."""

    def __init__(self, permissions: Any, controller: Any = None) -> None:
        self._permissions = permissions
        if controller is None:
            from .controller import ComputerController

            controller = ComputerController()
        self._controller = controller

        # Subsystems, all deterministic and offline.
        self._resolver = ElementResolver(
            vision=getattr(controller, "vision", None),
            screen=getattr(controller, "screen", None),
        )
        self._state = StateManager(
            windows=getattr(controller, "windows", None),
            mouse=getattr(controller, "mouse", None),
        )
        self._verifier = VerificationEngine(
            vision=getattr(controller, "vision", None),
            windows=getattr(controller, "windows", None),
        )
        self._recovery = RecoveryEngine(controller=controller, state=self._state)
        self._dispatcher = SkillDispatcher(
            controller=controller,
            resolver=self._resolver,
            state=self._state,
            permissions=permissions,
            registry=REGISTRY,
            verifier=self._verifier,
            recovery=self._recovery,
        )

    # --- public API ----------------------------------------------------------
    def run_skill(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """Execute a skill / semantic UI verb with verification and recovery."""
        # Keep engine memory fresh before acting so state-aware skills are right.
        self._state.refresh()
        return self._dispatcher.dispatch(name, params, expected)

    def state(self) -> ComputerState:
        """Current engine memory (refreshed from the live desktop)."""
        return self._state.refresh()

    def see(self, window_title: str | None = None) -> str:
        """A semantic snapshot (element descriptions + text) for replanning."""
        return self._controller.see(window_title)

    def catalog(self, max_level: PermissionLevel | None = None) -> str:
        """Skill manifest text for the AI, hiding skills above ``max_level``."""
        if max_level is None:
            max_level = self._permissions.level
        return REGISTRY.manifest(max_level=max_level)

    @property
    def controller(self) -> Any:
        return self._controller

    @property
    def state_manager(self) -> StateManager:
        return self._state
