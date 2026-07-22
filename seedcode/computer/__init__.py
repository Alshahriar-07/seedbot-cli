"""Computer Engine: safe, permissioned control of the local desktop.

The engine gives agent mode "hands and eyes" on the machine: mouse, keyboard,
screenshots, window management, application launch/close, and the registry.
Everything is Windows-only in this release and every dependency is optional
(``pip install seedcode-cli[desktop]``) — the rest of Seed Code must import
this package safely on any platform, so all heavy imports happen lazily and
:func:`is_available` is the single gate callers consult first.

Layout mirrors the tool engine philosophy: small driver modules
(:mod:`mouse`, :mod:`keyboard`, :mod:`screen`, :mod:`windows`, :mod:`vision`,
:mod:`registry`) wrap the libraries, :mod:`permissions` owns the Desktop
Control grant flow, and :class:`~seedcode.computer.controller.ComputerController`
is the façade the tools talk to.
"""

from __future__ import annotations

import importlib.util
import sys

from typing import TYPE_CHECKING, Any

from .permissions import DesktopGrant, DesktopSession

if TYPE_CHECKING:
    from .engine import ComputerEngine

__all__ = [
    "DesktopGrant",
    "DesktopSession",
    "REQUIRED_PACKAGES",
    "is_available",
    "missing_packages",
    "get_engine",
    "reset_engine",
]

# import name -> pip name (what to install when missing).
REQUIRED_PACKAGES: dict[str, str] = {
    "pyautogui": "pyautogui",
    "mss": "mss",
    "pygetwindow": "pygetwindow",
    "uiautomation": "uiautomation",
    "PIL": "pillow",
}

INSTALL_HINT = "pip install seedcode-cli[desktop]"


def missing_packages() -> list[str]:
    """Pip names of desktop dependencies that are not importable."""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_name)
    return missing


def is_available() -> tuple[bool, str]:
    """Whether desktop control can run here; (ok, human-readable reason)."""
    if sys.platform != "win32":
        return False, "Desktop control is Windows-only in this release."
    missing = missing_packages()
    if missing:
        return (
            False,
            f"Missing packages: {', '.join(missing)}. Install with: {INSTALL_HINT}",
        )
    return True, "Desktop control is available."


# One Computer Engine per session, created lazily so importing this package is
# free on any platform and the (heavy) drivers only load when first used.
_ENGINE: "ComputerEngine | None" = None


def get_engine(permissions: Any, controller: Any = None) -> "ComputerEngine":
    """Return the session's :class:`ComputerEngine`, creating it on first use."""
    global _ENGINE
    if _ENGINE is None:
        from .engine import ComputerEngine

        _ENGINE = ComputerEngine(permissions=permissions, controller=controller)
    return _ENGINE


def reset_engine() -> None:
    """Drop the cached engine (called when the session/permissions change)."""
    global _ENGINE
    _ENGINE = None
