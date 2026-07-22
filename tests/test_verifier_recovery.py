"""Tests for the verification and recovery engines."""

from __future__ import annotations

from seedcode.computer.recovery import RecoveryEngine, RecoveryOutcome
from seedcode.computer.verifier import VerificationEngine, VerifyResult


class _Win:
    def __init__(self, title):
        self.title = title

    def describe(self):
        return self.title


class _FakeWindows:
    def __init__(self, titles):
        self._titles = list(titles)

    def list_windows(self):
        return [_Win(t) for t in self._titles]


class _El:
    def __init__(self, role, name):
        self.role = role
        self.name = name
        self.x = 1
        self.y = 1
        self.enabled = True


class _FakeVision:
    def __init__(self, elements):
        self._elements = elements

    def snapshot(self, window_title=None):
        return ("W", self._elements)

    def ocr_available(self):
        return False


def _fast_verifier(**kw):
    # Zero timeout so failing checks don't poll for seconds.
    return VerificationEngine(timeout_s=0.0, poll_s=0.0, **kw)


# --- verifier ---------------------------------------------------------------

def test_verify_no_expectation_passes():
    v = _fast_verifier(windows=_FakeWindows([]), vision=_FakeVision([]))
    assert v.verify(None).ok
    assert v.verify({}).ok


def test_verify_window_present():
    v = _fast_verifier(windows=_FakeWindows(["Untitled - Notepad"]), vision=_FakeVision([]))
    assert v.verify({"window": "Notepad"}).ok


def test_verify_window_missing_fails():
    v = _fast_verifier(windows=_FakeWindows(["Calculator"]), vision=_FakeVision([]))
    res = v.verify({"window": "Notepad"})
    assert not res.ok
    assert "no window" in res.detail.lower()


def test_verify_window_gone():
    v = _fast_verifier(windows=_FakeWindows(["Calculator"]), vision=_FakeVision([]))
    assert v.verify({"window_gone": "Notepad"}).ok
    assert not v.verify({"window_gone": "Calculator"}).ok


def test_verify_text_on_screen():
    v = _fast_verifier(windows=_FakeWindows([]), vision=_FakeVision([_El("text", "Welcome back")]))
    assert v.verify({"text": "welcome"}).ok
    assert not v.verify({"text": "goodbye"}).ok


def test_verify_file_exists(tmp_path):
    f = tmp_path / "out.txt"
    f.write_text("hi")
    v = _fast_verifier(windows=_FakeWindows([]), vision=_FakeVision([]))
    assert v.verify({"file_exists": str(f)}).ok
    assert not v.verify({"file_exists": str(tmp_path / "nope.txt")}).ok


def test_verify_result_is_boolean():
    assert bool(VerifyResult(True, "x")) is True
    assert bool(VerifyResult(False, "x")) is False


# --- recovery ---------------------------------------------------------------

class _FakeController:
    """Records recovery nudges; the action succeeds after N attempts."""

    def __init__(self, succeed_after):
        self._succeed_after = succeed_after
        self.attempts = 0
        self.calls = []

    def wait(self, s):
        self.calls.append(("wait", s))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def focus_window(self, title):
        self.calls.append(("focus", title))

    def see(self, title=None):
        self.calls.append(("see", title))


def test_recovery_succeeds_after_refocus():
    ctrl = _FakeController(succeed_after=2)

    def action():
        ctrl.attempts += 1
        return "did it"

    def verify():
        return VerifyResult(ctrl.attempts >= 2, "checked")

    eng = RecoveryEngine(controller=ctrl)
    outcome = eng.recover(action, verify, window_title="Notepad")
    assert outcome.recovered
    assert outcome.strategies_tried  # at least one strategy ran


def test_recovery_exhausts_and_reports():
    ctrl = _FakeController(succeed_after=999)

    def action():
        return "tried"

    def verify():
        return VerifyResult(False, "never true")

    eng = RecoveryEngine(controller=ctrl)
    outcome = eng.recover(action, verify, window_title="X", app_target="app.exe")
    assert not outcome.recovered
    assert isinstance(outcome, RecoveryOutcome)
    assert len(outcome.strategies_tried) >= 3  # walked the full ladder
