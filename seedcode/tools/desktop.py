"""Desktop tools: the Computer Engine's AI-facing contract.

This module is the *entire* surface the AI has on the local machine, and it is
deliberately narrow. The AI reasons and decides; the deterministic
:class:`~seedcode.computer.engine.ComputerEngine` does the work. So the AI never
moves the mouse, presses keys, waits for windows, retries, or handles OCR —
those live below this line.

What the AI can call:

* ``computer_run`` — run a high-level skill from the catalog (the main verb).
* ``ui_click`` / ``ui_double_click`` / ``ui_right_click`` / ``ui_type`` /
  ``ui_wait_for`` / ``ui_assert`` — semantic UI actions whose targets are
  *descriptions* ("the Submit button"); the engine resolves coordinates.
* ``computer_state`` — read engine memory (focused app, pointer, recent work).
* ``computer_see`` — a semantic snapshot to replan against unknown UI.
* ``desktop_screenshot`` / ``desktop_windows`` / ``desktop_screen_info`` —
  observation for vision providers and replanning.

No coordinate-, keystroke-, or selector-bearing argument is exposed. Capability
is gated by the unified :class:`~seedcode.tools.permissions.PermissionLevel`
(desktop needs ``DESKTOP``; sensitive skills need ``FULL_SYSTEM``), and every
sensitive action is confirmed per-action through the session's Desktop Control
gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ToolError, ToolResult, register
from .permissions import PermissionLevel

if TYPE_CHECKING:
    from ..computer.engine import ComputerEngine
    from .permissions import PermissionManager


# Shared lazy controller: one instance per session, reused by the engine and
# by the hand commands (/screenshot, /windows, /computer) that don't need a
# permission gate. Built on first use so importing this module never pulls in
# the desktop libraries.
_controller: "Any | None" = None


def get_controller() -> "Any":
    """Return the shared :class:`ComputerController`, building it on first use."""
    global _controller
    if _controller is None:
        from ..computer.controller import ComputerController

        _controller = ComputerController()
    return _controller


def reset_controller() -> None:
    """Drop the cached controller and engine (tests inject fakes via this)."""
    global _controller
    _controller = None
    from ..computer import reset_engine

    reset_engine()


def _engine(perm: "PermissionManager") -> "ComputerEngine":
    """Return the session Computer Engine, or raise a model-readable error."""
    from ..computer import get_engine, is_available

    if not perm.level.allows_desktop:
        raise ToolError(
            "Desktop control needs Desktop permission or higher. The user can "
            "enable it with /assist on or raise it with /permission desktop."
        )
    if perm.desktop is None or not perm.desktop.enabled:
        raise ToolError(
            "Desktop tools are disabled. The user can enable them with /assist on."
        )
    ok, reason = is_available()
    if not ok:
        raise ToolError(f"Desktop control is unavailable: {reason}")
    return get_engine(perm, controller=get_controller())


def _confirm_sensitive(perm: "PermissionManager", skill_name: str, params: dict) -> None:
    """Per-action confirmation for sensitive skills, via the Desktop gate.

    Sensitive skills additionally require Full System and are never remembered
    ("Always" is downgraded to "Once" by the gate), so each one is approved
    individually.
    """
    from ..computer.permissions import CATEGORY_SYSTEM

    perm.require(PermissionLevel.FULL_SYSTEM, f"sensitive skill '{skill_name}'")
    desc = f"{skill_name} {params}".strip()
    perm.desktop.check(CATEGORY_SYSTEM, desc)  # type: ignore[union-attr]


def _gate_control(perm: "PermissionManager", description: str) -> None:
    """Non-sensitive desktop confirmation (remembered per session)."""
    from ..computer.permissions import CATEGORY_CONTROL

    perm.desktop.check(CATEGORY_CONTROL, description)  # type: ignore[union-attr]


def _dispatch(perm: "PermissionManager", name: str, params: dict[str, Any],
              expected: dict[str, Any] | None = None) -> ToolResult:
    """Shared path for skills and semantic actions: gate, run, report."""
    from ..computer.skills import REGISTRY

    engine = _engine(perm)
    skill = REGISTRY.get(name)
    if skill is not None and skill.sensitive:
        _confirm_sensitive(perm, skill.name, params)
    else:
        _gate_control(perm, f"{name} {params}".strip())

    result = engine.run_skill(name, params, expected)
    _queue_screenshot(perm)
    return ToolResult(result.ok, result.for_model())


# --- primary verb: run a skill ----------------------------------------------
@register(
    "computer_run",
    "Run a high-level Computer Engine skill by name (e.g. launch_app, "
    "google_search, create_python_project). The engine expands it into "
    "verified, deterministic steps and recovers from failures on its own — you "
    "choose the skill and its parameters, nothing lower-level. See the skill "
    "catalog in the system prompt for available skills.",
    {
        "skill": "skill name from the catalog",
        "params": "(optional) object of the skill's parameters",
        "expected": "(optional) outcome to verify, e.g. {\"window\": \"Notepad\"}",
    },
    mutates=True,
    group="desktop",
    types={"params": "object", "expected": "object"},
)
def _computer_run(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    name = str(args.get("skill", "")).strip()
    if not name:
        return ToolResult(False, "skill is required.")
    params = args.get("params") or {}
    if not isinstance(params, dict):
        return ToolResult(False, "params must be an object.")
    expected = args.get("expected")
    if expected is not None and not isinstance(expected, dict):
        return ToolResult(False, "expected must be an object.")
    return _dispatch(perm, name, params, expected)


# --- semantic UI actions (descriptions, never coordinates) -------------------
def _semantic(perm: "PermissionManager", verb: str, args: dict[str, Any]) -> ToolResult:
    target = str(args.get("target", "")).strip()
    if not target:
        return ToolResult(False, "target description is required.")
    params: dict[str, Any] = {"target": target}
    if "text" in args:
        params["text"] = args.get("text", "")
    if "secret" in args:
        params["secret"] = str(args.get("secret", "")).lower() in ("true", "1", "yes")
    return _dispatch(perm, verb, params)


@register(
    "ui_click",
    "Click a UI element described in plain words (e.g. \"the Save button\"). "
    "The engine locates it — never pass coordinates.",
    {"target": "description of the element to click"},
    mutates=True,
    group="desktop",
)
def _ui_click(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return _semantic(perm, "ui_click", args)


@register(
    "ui_double_click",
    "Double-click a described UI element (e.g. \"the project folder\").",
    {"target": "description of the element to double-click"},
    mutates=True,
    group="desktop",
)
def _ui_double_click(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return _semantic(perm, "ui_double_click", args)


@register(
    "ui_right_click",
    "Right-click a described UI element to open its context menu.",
    {"target": "description of the element to right-click"},
    mutates=True,
    group="desktop",
)
def _ui_right_click(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return _semantic(perm, "ui_right_click", args)


@register(
    "ui_type",
    "Type text into a described field (e.g. \"the search box\"). Set secret=true "
    "for passwords. The engine focuses the field and types — no coordinates.",
    {
        "target": "description of the field to type into",
        "text": "the text to type",
        "secret": "(optional) true when the text is a password or secret",
    },
    mutates=True,
    group="desktop",
)
def _ui_type(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    if "text" not in args:
        return ToolResult(False, "text is required.")
    return _semantic(perm, "ui_type", args)


@register(
    "ui_wait_for",
    "Wait until a described element or window appears before continuing.",
    {"target": "description of what to wait for"},
    mutates=False,
    group="desktop",
)
def _ui_wait_for(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return _semantic(perm, "ui_wait_for", args)


@register(
    "ui_assert",
    "Check that a described element or text is present, without acting on it.",
    {"target": "description of what should be present"},
    mutates=False,
    group="desktop",
)
def _ui_assert(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    return _semantic(perm, "ui_assert", args)


# --- observation -------------------------------------------------------------
@register(
    "computer_state",
    "Read the Computer Engine's memory: focused app/window, pointer, clipboard, "
    "terminal directory, current project, and recent actions. Prefer this over "
    "re-inspecting the screen — the engine tracks state for you.",
    {},
    mutates=False,
    group="desktop",
)
def _computer_state(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    engine = _engine(perm)
    return ToolResult(True, engine.state().describe())


@register(
    "computer_see",
    "Get a semantic snapshot of the active (or named) window: the elements and "
    "visible text, described in words. Use this to replan when the UI is "
    "unfamiliar. Returns descriptions, never coordinates.",
    {"window": "(optional) part of a window title; default: the active window"},
    mutates=False,
    group="desktop",
)
def _computer_see(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    engine = _engine(perm)
    window = str(args.get("window", "") or "").strip() or None
    _gate_control(perm, f"inspect UI of {window or 'the active window'}")
    out = engine.see(window)
    _queue_screenshot(perm)
    return ToolResult(True, out)


@register(
    "desktop_screenshot",
    "Capture a screenshot (whole desktop, a monitor, or a region) to a PNG "
    "file; optionally OCR its text.",
    {
        "monitor": "(optional) 1-based monitor number",
        "region": "(optional) [left, top, width, height]",
        "ocr": "(optional) true to also extract text via OCR",
    },
    mutates=False,
    group="desktop",
)
def _desktop_screenshot(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    engine = _engine(perm)
    _gate_control(perm, "take a screenshot")
    controller = engine.controller

    region = None
    raw_region = args.get("region")
    if raw_region is not None:
        try:
            left, top, width, height = (int(v) for v in raw_region)
            region = (left, top, width, height)
        except (TypeError, ValueError):
            return ToolResult(False, "region must be [left, top, width, height] integers.")
    monitor = None
    if args.get("monitor") is not None:
        try:
            monitor = int(args["monitor"])
        except (TypeError, ValueError):
            return ToolResult(False, "monitor must be an integer (1-based).")

    try:
        path = controller.screenshot(region=region, monitor=monitor)
    except Exception as exc:
        return ToolResult(False, f"Screenshot failed: {exc}")
    output = f"Screenshot saved: {path}"
    if str(args.get("ocr", "")).lower() in ("true", "1", "yes"):
        output += "\n[OCR]\n" + controller.vision.ocr_screenshot(path)
    _queue_screenshot(perm, str(path))
    return ToolResult(True, output)


@register(
    "desktop_windows",
    "List all open windows with their titles, positions, and sizes.",
    {},
    mutates=False,
    group="desktop",
)
def _desktop_windows(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    engine = _engine(perm)
    _gate_control(perm, "list open windows")
    try:
        return ToolResult(True, engine.controller.list_windows())
    except Exception as exc:
        return ToolResult(False, f"Could not list windows: {exc}")


@register(
    "desktop_screen_info",
    "Report screen resolution and multi-monitor layout.",
    {},
    mutates=False,
    group="desktop",
)
def _desktop_screen_info(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    engine = _engine(perm)
    _gate_control(perm, "read screen info")
    try:
        return ToolResult(True, engine.controller.screen_info())
    except Exception as exc:
        return ToolResult(False, f"Could not read screen info: {exc}")


# --- screenshot hand-off to the agent loop -----------------------------------
def _queue_screenshot(perm: "PermissionManager", path: str | None = None) -> None:
    """Queue a screenshot for image-capable providers (best-effort).

    The agent loop attaches the encoded image to the next tool-results message
    when the active provider supports vision. Failure here never fails a tool.
    """
    desktop = perm.desktop
    if desktop is None:
        return
    try:
        from ..computer import screen

        if path is None:
            path = str(screen.capture())
        desktop.pending_images.append(screen.encode_png_base64(path))
        del desktop.pending_images[:-1]  # keep only the latest frame
    except Exception:
        pass
