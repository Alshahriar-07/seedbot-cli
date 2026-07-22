"""ComputerController: the façade the desktop tools drive.

Owns the driver modules (injectable for tests), validates every coordinate
against the live virtual-desktop geometry (never a blind click), paces
actions, and verifies each mutating action by reporting post-action state —
the active window and the element under the pointer — so the agent loop can
confirm outcomes instead of assuming them. Focus operations retry once
before surfacing a failure.
"""

from __future__ import annotations

import time
from typing import Any

from ..utils.logger import get_logger
from . import browser as browser_driver
from . import keyboard as keyboard_driver
from . import mouse as mouse_driver
from . import registry as registry_driver
from . import screen as screen_driver
from . import vision as vision_driver
from . import windows as windows_driver

_log = get_logger("computer")

# One agent turn may not wait forever; desktop_wait is clamped to this.
MAX_WAIT_S = 30.0
# Settle time after mutating actions before state is read for verification.
_VERIFY_DELAY_S = 0.3


class ComputerError(Exception):
    """A desktop action failed; the message is fed back to the model."""


class ComputerController:
    """High-level desktop actions with validation and built-in verification."""

    def __init__(
        self,
        mouse: Any = mouse_driver,
        keyboard: Any = keyboard_driver,
        screen: Any = screen_driver,
        windows: Any = windows_driver,
        vision: Any = vision_driver,
        registry: Any = registry_driver,
        browser: Any = browser_driver,
    ) -> None:
        self.mouse = mouse
        self.keyboard = keyboard
        self.screen = screen
        self.windows = windows
        self.vision = vision
        self.registry = registry
        self.browser = browser

    # --- coordinates ---------------------------------------------------------
    def validate_point(self, x: Any, y: Any) -> tuple[int, int]:
        """Coerce and bounds-check a coordinate pair against the desktop."""
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError):
            raise ComputerError(f"Coordinates must be integers, got ({x!r}, {y!r}).")
        geo = self.screen.geometry()
        if not geo.contains(px, py):
            raise ComputerError(
                f"({px}, {py}) is outside the desktop "
                f"({geo.left}..{geo.left + geo.width - 1}, "
                f"{geo.top}..{geo.top + geo.height - 1}). "
                "Take a fresh desktop_see snapshot for current coordinates."
            )
        return px, py

    # --- verification helpers ------------------------------------------------
    def _state_after(self, x: int | None = None, y: int | None = None) -> str:
        """Post-action state line appended to every mutating result."""
        time.sleep(_VERIFY_DELAY_S)
        active = self.windows.active_window()
        parts = [f"active window: {active.describe() if active else '(none)'}"]
        if x is not None and y is not None:
            parts.append(f"element at ({x}, {y}): {self.vision.element_at(x, y)}")
        return "[verify] " + "; ".join(parts)

    # --- mouse ---------------------------------------------------------------
    def mouse_move(self, x: Any, y: Any) -> str:
        px, py = self.validate_point(x, y)
        self.mouse.move(px, py)
        return f"Moved pointer to ({px}, {py}).\n" + self._state_after(px, py)

    def mouse_click(self, x: Any, y: Any, button: str = "left", double: bool = False) -> str:
        px, py = self.validate_point(x, y)
        if button not in ("left", "right"):
            raise ComputerError("button must be 'left' or 'right'.")
        self.mouse.click(px, py, button=button, double=double)
        kind = "Double-clicked" if double else f"{button.capitalize()}-clicked"
        return f"{kind} at ({px}, {py}).\n" + self._state_after(px, py)

    def mouse_drag(self, x1: Any, y1: Any, x2: Any, y2: Any) -> str:
        sx, sy = self.validate_point(x1, y1)
        ex, ey = self.validate_point(x2, y2)
        self.mouse.drag(sx, sy, ex, ey)
        return f"Dragged ({sx}, {sy}) -> ({ex}, {ey}).\n" + self._state_after(ex, ey)

    def mouse_scroll(self, amount: Any, x: Any = None, y: Any = None) -> str:
        try:
            notches = int(amount)
        except (TypeError, ValueError):
            raise ComputerError(f"Scroll amount must be an integer, got {amount!r}.")
        notches = max(-50, min(50, notches))
        point = None
        if x is not None and y is not None:
            point = self.validate_point(x, y)
        self.mouse.scroll(notches, *(point or (None, None)))
        where = f" at {point}" if point else ""
        return f"Scrolled {notches} notches{where}.\n" + self._state_after(*(point or (None, None)))

    # --- keyboard ------------------------------------------------------------
    def type_text(self, text: str) -> str:
        try:
            self.keyboard.type_text(str(text))
        except ValueError as exc:
            raise ComputerError(str(exc))
        shown = str(text) if len(str(text)) <= 60 else str(text)[:60] + "..."
        return f"Typed {len(str(text))} chars ({shown!r}).\n" + self._state_after()

    def hotkey(self, keys: list[str]) -> str:
        try:
            self.keyboard.hotkey([str(k) for k in keys])
        except ValueError as exc:
            raise ComputerError(str(exc))
        return f"Pressed {'+'.join(str(k) for k in keys)}.\n" + self._state_after()

    # --- windows -------------------------------------------------------------
    def list_windows(self) -> str:
        windows = self.windows.list_windows()
        if not windows:
            return "No open windows found."
        return "Open windows:\n" + "\n".join(f"  - {w.describe()}" for w in windows)

    def focus_window(self, title: str) -> str:
        """Focus with one retry — Windows foreground rules are flaky."""
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                self.windows.focus_window(title)
                time.sleep(_VERIFY_DELAY_S)
                active = self.windows.active_window()
                if active and title.strip().lower() in active.title.lower():
                    return f"Focused window.\n[verify] active window: {active.describe()}"
                last_error = None
            except Exception as exc:
                last_error = exc
            time.sleep(0.4)  # let the window manager settle, then retry
        if last_error is not None:
            raise ComputerError(f"Could not focus '{title}': {last_error}")
        active = self.windows.active_window()
        raise ComputerError(
            f"Focus did not stick on '{title}'. Active window is "
            f"{active.describe() if active else '(none)'} — check desktop_windows."
        )

    def open_app(self, target: str) -> str:
        try:
            message = self.windows.open_app(target)
        except Exception as exc:
            raise ComputerError(str(exc))
        time.sleep(1.0)  # give the app a moment to show a window
        return message + "\n" + self._state_after()

    def close_app(self, title: str, force: bool = False) -> str:
        try:
            message = self.windows.close_window(title, force=force)
        except Exception as exc:
            raise ComputerError(str(exc))
        return message + "\n" + self._state_after()

    # --- screen & vision -----------------------------------------------------
    def screenshot(
        self,
        region: tuple[int, int, int, int] | None = None,
        monitor: int | None = None,
        save_to=None,
    ) -> str:
        try:
            path = self.screen.capture(region=region, monitor=monitor, save_to=save_to)
        except Exception as exc:
            raise ComputerError(f"Screenshot failed: {exc}")
        return str(path)

    def screen_info(self) -> str:
        geo = self.screen.geometry()
        lines = [
            f"Virtual desktop: {geo.width}x{geo.height} at ({geo.left}, {geo.top})",
            f"Monitors: {len(geo.monitors)}",
        ]
        for m in geo.monitors:
            primary = " (primary)" if m.primary else ""
            lines.append(
                f"  - Monitor {m.index}: {m.width}x{m.height} at ({m.left}, {m.top}){primary}"
            )
        return "\n".join(lines)

    def see(self, window_title: str | None = None) -> str:
        """UI-tree snapshot: what is on screen, with clickable coordinates."""
        try:
            title, elements = self.vision.snapshot(window_title)
        except ValueError as exc:
            raise ComputerError(str(exc))
        except Exception as exc:
            raise ComputerError(f"Could not read the UI tree: {exc}")
        return self.vision.describe_snapshot(title, elements)

    def wait(self, seconds: Any) -> str:
        try:
            duration = float(seconds)
        except (TypeError, ValueError):
            raise ComputerError(f"Wait time must be a number, got {seconds!r}.")
        duration = max(0.0, min(duration, MAX_WAIT_S))
        time.sleep(duration)
        return f"Waited {duration:g}s.\n" + self._state_after()

    # --- registry ------------------------------------------------------------
    def registry_read(self, path: str, name: str = "") -> str:
        try:
            return self.registry.read_value(path, name)
        except FileNotFoundError:
            raise ComputerError(f"Registry key or value not found: {path} : {name}")
        except (ValueError, OSError, RuntimeError) as exc:
            raise ComputerError(f"Registry read failed: {exc}")

    def registry_list(self, path: str) -> str:
        try:
            return self.registry.list_key(path)
        except FileNotFoundError:
            raise ComputerError(f"Registry key not found: {path}")
        except (ValueError, OSError, RuntimeError) as exc:
            raise ComputerError(f"Registry list failed: {exc}")

    def registry_write(self, path: str, name: str, value: str, value_type: str) -> str:
        try:
            return self.registry.write_value(path, name, value, value_type)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ComputerError(f"Registry write failed: {exc}")

    def registry_delete(self, path: str, name: str) -> str:
        try:
            return self.registry.delete_value(path, name)
        except FileNotFoundError:
            raise ComputerError(f"Registry key or value not found: {path} : {name}")
        except (ValueError, OSError, RuntimeError) as exc:
            raise ComputerError(f"Registry delete failed: {exc}")

    # --- browser -------------------------------------------------------------
    def browser_navigate(self, url: str) -> str:
        """Navigate browser to URL."""
        try:
            return self.browser.navigate(url)
        except Exception as exc:
            raise ComputerError(f"Browser navigation failed: {exc}")

    def browser_click(self, selector: str, selector_type: str = "css") -> str:
        """Click element in browser."""
        try:
            return self.browser.click_element(selector, selector_type)
        except Exception as exc:
            raise ComputerError(f"Browser click failed: {exc}")

    def browser_type(self, selector: str, text: str, selector_type: str = "css") -> str:
        """Type into browser element."""
        try:
            return self.browser.type_in_element(selector, text, selector_type)
        except Exception as exc:
            raise ComputerError(f"Browser typing failed: {exc}")

    def browser_info(self) -> str:
        """Get current browser page info."""
        try:
            return self.browser.get_page_info()
        except Exception as exc:
            raise ComputerError(f"Browser info failed: {exc}")

    def browser_find(self, selector: str, selector_type: str = "css") -> str:
        """Find elements in browser."""
        try:
            return self.browser.find_elements(selector, selector_type)
        except Exception as exc:
            raise ComputerError(f"Browser find failed: {exc}")

    def browser_close(self) -> str:
        """Close browser."""
        try:
            return self.browser.close_browser()
        except Exception as exc:
            raise ComputerError(f"Browser close failed: {exc}")
