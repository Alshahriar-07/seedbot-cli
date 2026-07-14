"""Seed Code command-line entry point (``seedcode``).

Thin wrapper: builds the UI, hands off to the application controller
(:mod:`seedcode.app`), and provides the final safety net so a stray exception is
shown as a friendly message rather than a traceback.
"""

from __future__ import annotations

import sys

from .app import run
from .ui import UI


def main() -> None:
    """Console-script entry point (``seedcode``)."""
    ui = UI()
    try:
        run(ui)
    except KeyboardInterrupt:
        ui.blank()
        ui.dim("Interrupted.")
    except Exception as exc:  # final safety net — never show a traceback
        ui.error(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
