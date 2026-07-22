"""Seed Code command-line entry point (``seedcode``).

Thin wrapper: prepares the Windows console, builds the UI, hands off to the
application controller (:mod:`seedcode.app`), and provides the final safety
net so a stray exception is shown as a friendly message rather than a
traceback. Heavy imports are deferred into :func:`main` so ``--version``
(used by installers to verify the install) answers instantly.
"""

from __future__ import annotations

import sys


def _prepare_console() -> None:
    """Make stdout/stderr UTF-8-safe, primarily for Windows.

    Interactive Windows consoles accept Unicode natively (PEP 528), but a
    redirected stream falls back to the legacy ANSI code page (e.g. cp1252),
    where the banner's box-drawing characters would raise UnicodeEncodeError.
    Reconfiguring to UTF-8 with ``errors="replace"`` makes output safe in
    Windows Terminal, PowerShell, CMD, and when piped to files.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass  # exotic streams (tests, embedders) — never fatal


_HELP = """\
Seed Code - a terminal-based AI coding assistant. Plant ideas. Grow code.

Usage:
  seedcode              Start the interactive app (chat + menu)
  seedcode --version    Print the version and exit
  seedcode --help       Show this help and exit

Inside the app, type /help for commands: /provider, /model, /agent,
/permission, /settings, /doctor, and more.

Docs: https://github.com/Alshahriar-07/seedcode-cli
"""


def main() -> None:
    """Console-script entry point (``seedcode``)."""
    # --version/--help must work non-interactively and fast (installers and
    # scripts verify with them), so handle both before any UI, config, or
    # logging work happens.
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        from . import __version__

        print(f"Seed Code v{__version__}")
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(_HELP)
        return

    _prepare_console()

    from .utils.logger import get_logger, setup_logging

    setup_logging()
    log = get_logger("cli")

    from . import __version__

    log.info(
        "Seed Code v%s starting (python %s on %s)",
        __version__,
        sys.version.split()[0],
        sys.platform,
    )

    from .app import run
    from .ui import UI

    ui = UI()
    try:
        run(ui)
        log.info("Clean exit.")
    except KeyboardInterrupt:
        ui.blank()
        ui.dim("Interrupted.")
        log.info("Exited via Ctrl+C.")
    except Exception as exc:  # final safety net — never show a traceback
        log.exception("Fatal error")
        ui.error(f"Fatal error: {exc}")
        ui.dim("Details were logged to ~/.seedcode/logs/seedcode.log")
        sys.exit(1)


if __name__ == "__main__":
    main()
