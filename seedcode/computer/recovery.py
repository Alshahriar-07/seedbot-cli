"""Recovery engine: deterministic reflexes before the AI is asked to replan.

When an action fails verification, the dispatcher hands the situation to the
recovery engine, which walks a fixed ladder of local strategies — retry,
refocus the target window, dismiss a stray dialog, re-snapshot the UI, restart
the app — re-running the action after each. Only when every strategy is
exhausted does control return to the dispatcher, which then (and only then)
asks the AI planner to replan.

The engine is deterministic and offline: it composes existing controller
primitives and never calls an AI provider. Strategies are ordered from
cheapest/least disruptive to most disruptive so a transient hiccup is fixed
without, say, killing and relaunching an application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# The result of trying to recover: whether the action ultimately succeeded and
# the trail of strategies attempted (surfaced in logs and to the AI on replan).
@dataclass(slots=True)
class RecoveryOutcome:
    recovered: bool
    detail: str
    strategies_tried: list[str] = field(default_factory=list)


# An action is a zero-arg callable that performs the operation and returns a
# short result string; it raises on hard failure. A verify is a zero-arg
# callable returning a truthy VerifyResult-like object.
Action = Callable[[], str]
Verify = Callable[[], Any]


class RecoveryEngine:
    """Applies local recovery strategies to a failed, verified action."""

    def __init__(self, controller: Any = None, state: Any = None) -> None:
        self._controller = controller
        self._state = state

    def recover(
        self,
        action: Action,
        verify: Verify,
        *,
        window_title: str | None = None,
        app_target: str | None = None,
    ) -> RecoveryOutcome:
        """Try to make ``action`` verify, walking the strategy ladder.

        Each strategy nudges the environment, re-runs the action, then
        re-verifies. Returns as soon as verification passes.
        """
        tried: list[str] = []
        last = "no recovery strategies applied"
        for name, strategy in self._ladder(window_title, app_target):
            tried.append(name)
            try:
                strategy()
            except Exception:
                # A strategy that itself fails is not fatal — move to the next.
                continue
            try:
                action()
            except Exception as exc:
                last = f"retry after {name} raised: {exc}"
                continue
            result = verify()
            if result:
                return RecoveryOutcome(
                    True, f"recovered via {name}: {getattr(result, 'detail', 'ok')}", tried
                )
            last = f"still failing after {name}: {getattr(result, 'detail', result)}"
        return RecoveryOutcome(False, last, tried)

    def _ladder(
        self, window_title: str | None, app_target: str | None
    ) -> list[tuple[str, Callable[[], None]]]:
        """Ordered (name, strategy) pairs, cheapest and least disruptive first."""
        c = self._controller
        ladder: list[tuple[str, Callable[[], None]]] = []

        # 1) Plain retry: let transient timing settle.
        ladder.append(("retry", lambda: c.wait(0.5) if c else None))

        # 2) Dismiss a stray modal/tooltip that may be intercepting input.
        ladder.append(("dismiss_dialog", lambda: c.hotkey(["esc"]) if c else None))

        # 3) Refocus the intended window — the most common real cause.
        if window_title and c:
            ladder.append(("refocus_window", lambda: c.focus_window(window_title)))

        # 4) Re-snapshot the UI so the next resolve sees the current tree.
        if c:
            ladder.append(("resnapshot", lambda: c.see(window_title)))

        # 5) Restart the app: close then reopen, the most disruptive step.
        if app_target and c:
            def _restart() -> None:
                try:
                    c.close_app(app_target, force=False)
                except Exception:
                    pass
                c.wait(0.5)
                c.open_app(app_target)
                if window_title:
                    c.wait(0.5)
                    c.focus_window(window_title)

            ladder.append(("restart_app", _restart))

        return ladder
