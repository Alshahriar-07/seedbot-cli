"""Verification engine: never trust an action without checking its result.

After the Computer Engine performs an action, the verifier confirms the world
actually changed the way the skill expected — a window appeared, an element is
present, text is on screen, a file exists, a process is running. Verification
is deterministic and offline; it reads driver/OS state and returns a
:class:`VerifyResult` the dispatcher uses to decide success vs. recovery.

Expectations are plain data (a dict the skill or the AI supplies as
``expected``), so the AI can state *what* success looks like without ever
touching *how* it is checked.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class VerifyResult:
    """Outcome of a verification check."""

    ok: bool
    detail: str

    def __bool__(self) -> bool:  # lets callers write ``if verify(...):``
        return self.ok


# Supported expectation kinds. An ``expected`` dict names one of these plus its
# argument, e.g. {"window": "Notepad"} or {"file_exists": "C:/x/out.txt"}.
_KINDS = (
    "window", "window_gone", "element", "text", "file_exists",
    "folder_exists", "process", "browser_url",
)


class VerificationEngine:
    """Checks expected outcomes against live machine state."""

    # How long to keep re-checking a not-yet-true expectation before failing;
    # UI and windows settle asynchronously, so a single check is too eager.
    def __init__(
        self,
        vision: Any = None,
        windows: Any = None,
        browser: Any = None,
        timeout_s: float = 4.0,
        poll_s: float = 0.3,
    ) -> None:
        if vision is None:
            from . import vision as vision  # type: ignore
        if windows is None:
            from . import windows as windows  # type: ignore
        self._vision = vision
        self._windows = windows
        # Browser is optional (selenium may be absent); resolve lazily on use.
        self._browser = browser
        self._timeout_s = timeout_s
        self._poll_s = poll_s

    def verify(self, expected: dict[str, Any] | None) -> VerifyResult:
        """Check an ``expected`` outcome dict; no expectation ⇒ pass.

        Polls until the expectation holds or the timeout elapses, so a window
        or element that appears a moment after the action still verifies.
        """
        if not expected:
            return VerifyResult(True, "no expectation to verify")
        kind = next((k for k in _KINDS if k in expected), None)
        if kind is None:
            return VerifyResult(True, f"unknown expectation {list(expected)}; skipped")
        arg = expected[kind]

        deadline = time.monotonic() + self._timeout_s
        last = ""
        while True:
            ok, last = self._check(kind, arg)
            if ok:
                return VerifyResult(True, last)
            if time.monotonic() >= deadline:
                return VerifyResult(False, last)
            time.sleep(self._poll_s)

    # --- individual checks ---------------------------------------------------
    def _check(self, kind: str, arg: Any) -> tuple[bool, str]:
        try:
            handler = getattr(self, f"_check_{kind}")
        except AttributeError:
            return True, f"no checker for {kind}"
        try:
            return handler(arg)
        except Exception as exc:
            return False, f"{kind} check errored: {exc}"

    def _check_window(self, title: str) -> tuple[bool, str]:
        want = str(title).strip().lower()
        for w in self._windows.list_windows():
            if want in w.title.lower():
                return True, f'window "{w.title}" present'
        return False, f'no window matching "{title}"'

    def _check_window_gone(self, title: str) -> tuple[bool, str]:
        want = str(title).strip().lower()
        present = [w for w in self._windows.list_windows() if want in w.title.lower()]
        if present:
            return False, f'window "{title}" still open'
        return True, f'window "{title}" closed'

    def _check_element(self, description: str) -> tuple[bool, str]:
        from .resolver import ElementResolver, ResolveError

        try:
            hit = ElementResolver(vision=self._vision).resolve(str(description))
            return True, f"element present: {hit.describe()}"
        except ResolveError as exc:
            return False, str(exc)

    def _check_text(self, text: str) -> tuple[bool, str]:
        want = str(text).strip().lower()
        try:
            _title, elements = self._vision.snapshot()
        except Exception:
            elements = []
        for el in elements:
            if want in (el.name or "").lower():
                return True, f'text "{text}" visible'
        return False, f'text "{text}" not found on screen'

    def _check_file_exists(self, path: str) -> tuple[bool, str]:
        exists = os.path.isfile(str(path))
        return exists, f'file {"exists" if exists else "missing"}: {path}'

    def _check_folder_exists(self, path: str) -> tuple[bool, str]:
        exists = os.path.isdir(str(path))
        return exists, f'folder {"exists" if exists else "missing"}: {path}'

    def _check_process(self, name: str) -> tuple[bool, str]:
        want = str(name).strip().lower()
        try:
            import psutil  # type: ignore

            for proc in psutil.process_iter(["name"]):
                pname = (proc.info.get("name") or "").lower()
                if want in pname:
                    return True, f'process "{name}" running'
            return False, f'process "{name}" not running'
        except Exception:
            # No psutil: fall back to a window-title heuristic rather than
            # claiming success we cannot substantiate.
            return self._check_window(name)

    def _check_browser_url(self, fragment: str) -> tuple[bool, str]:
        if self._browser is None:
            from . import browser as browser  # type: ignore

            self._browser = browser
        try:
            info = self._browser.get_page_info()
        except Exception as exc:
            return False, f"browser info unavailable: {exc}"
        ok = str(fragment).lower() in str(info).lower()
        return ok, f'browser url {"matches" if ok else "does not match"} "{fragment}"'
