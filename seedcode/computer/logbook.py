"""Structured execution log for the Computer Engine.

Every run through the dispatcher records what actually happened — the skill
chosen, the deterministic steps taken, whether verification passed, which
recovery strategies were used, and the final status — as an ordered list of
:class:`LogEntry` records. This is the engine's honest account of its own work:
the dispatcher writes it, the AI reads a compact rendering of it, and nothing
in it is fabricated. Success is only ever recorded when verification actually
passed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum


class Stage(str, Enum):
    PLAN = "plan"            # a skill/action was selected
    EXECUTE = "execute"     # deterministic steps ran
    VERIFY = "verify"       # outcome checked
    RECOVER = "recover"     # recovery strategies attempted
    DONE = "done"           # final status
    ERROR = "error"         # hard failure


@dataclass(slots=True)
class LogEntry:
    stage: Stage
    message: str
    ok: bool = True

    def render(self) -> str:
        mark = "✓" if self.ok else "✗"
        return f"{mark} [{self.stage.value}] {self.message}"


@dataclass
class ExecutionLog:
    """An append-only trail of a single dispatched request."""

    entries: list[LogEntry] = field(default_factory=list)

    def add(self, stage: Stage, message: str, ok: bool = True) -> None:
        self.entries.append(LogEntry(stage, message, ok))

    def plan(self, message: str) -> None:
        self.add(Stage.PLAN, message)

    def execute(self, message: str, ok: bool = True) -> None:
        self.add(Stage.EXECUTE, message, ok)

    def verify(self, message: str, ok: bool = True) -> None:
        self.add(Stage.VERIFY, message, ok)

    def recover(self, message: str, ok: bool = True) -> None:
        self.add(Stage.RECOVER, message, ok)

    def done(self, message: str, ok: bool = True) -> None:
        self.add(Stage.DONE if ok else Stage.ERROR, message, ok)

    @property
    def succeeded(self) -> bool:
        """True only if a DONE (not ERROR) entry was recorded and nothing failed."""
        return any(e.stage is Stage.DONE and e.ok for e in self.entries)

    def render(self) -> str:
        return "\n".join(e.render() for e in self.entries)

    def summary(self) -> str:
        """One-line result for the AI: the final DONE/ERROR message."""
        for e in reversed(self.entries):
            if e.stage in (Stage.DONE, Stage.ERROR):
                return e.message
        return self.entries[-1].message if self.entries else "nothing happened"

    def persist(self, label: str = "") -> None:
        """Append this run to ``~/.seedcode/logs/execution-<date>.jsonl``.

        Best-effort: a full disk or locked file must never fail the action the
        log describes. One JSON line per dispatched request keeps the file
        greppable and machine-readable.
        """
        try:
            from ..utils.helpers import app_dir

            logs = app_dir() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            path = logs / time.strftime("execution-%Y%m%d.jsonl", time.localtime())
            record = {
                "ts": round(time.time(), 3),
                "label": label,
                "ok": self.succeeded,
                "stages": [
                    {"stage": e.stage.value, "ok": e.ok, "message": e.message}
                    for e in self.entries
                ],
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # logging is evidence, not a dependency
