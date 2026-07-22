"""Terminal execution tool: run a shell command in the workspace, live.

Commands run through ``subprocess.Popen`` with a reader thread so output
streams line-by-line while the process is still running (Windows pipes have
no ``select``, hence the thread + queue). The agent layer can attach a
per-line callback via ``PermissionManager.on_output`` to echo progress to
the user as it happens.

Shell selection: ``cmd``, ``powershell`` and ``bash`` are supported
explicitly; the default ("") is the platform shell (cmd on Windows,
/bin/sh elsewhere) via ``shell=True``.

Cancellation: pressing Ctrl+C while a command is running kills that
command's whole process tree (``taskkill /T /F`` on Windows, process-group
SIGKILL elsewhere) and reports the cancellation as a failed tool result —
the agent turn itself continues, so the model learns the command was
cancelled instead of the loop dying.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import IO, TYPE_CHECKING, Any, Callable

from .base import MAX_OUTPUT_CHARS, ToolResult, int_arg, register
from .permissions import CATEGORY_SHELL

if TYPE_CHECKING:
    from .permissions import PermissionManager

_DEFAULT_TIMEOUT_S = 60
_MAX_TIMEOUT_S = 300

# Explicit shell -> argv builder. "" (default) uses shell=True instead.
_SHELLS: dict[str, Callable[[str], list[str]]] = {
    "cmd": lambda c: ["cmd", "/d", "/c", c],
    "powershell": lambda c: [
        "powershell", "-NoProfile", "-NonInteractive", "-Command", c
    ],
    "bash": lambda c: ["bash", "-lc", c],
}

_EOF = object()  # sentinel the reader thread puts when the pipe closes


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill a process and all of its children; never raises."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _reader(pipe: IO[str], out: "queue.Queue[object]") -> None:
    """Pump lines from the child's merged stdout into the queue."""
    try:
        for line in pipe:
            out.put(line)
    except (OSError, ValueError):
        pass  # pipe closed mid-read; treat as EOF
    out.put(_EOF)


def run_command(
    perm: "PermissionManager",
    command: str,
    timeout_s: int,
    *,
    shell: str = "",
    on_line: Callable[[str], None] | None = None,
) -> ToolResult:
    """Shared runner (the git tool reuses it for real git invocations).

    ``on_line`` receives each output line (rstripped) as it arrives; when
    None, ``perm.on_output`` is used so the app layer's live echo applies
    everywhere.
    """
    timeout_s = max(1, min(int(timeout_s), _MAX_TIMEOUT_S))
    on_line = on_line or perm.on_output

    if shell:
        builder = _SHELLS.get(shell.strip().lower())
        if builder is None:
            choices = ", ".join(sorted(_SHELLS))
            return ToolResult(False, f"Unknown shell '{shell}'. Choose one of: {choices}.")
        popen_args: str | list[str] = builder(command)
        use_shell = False
    else:
        popen_args = command
        use_shell = True

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # Own process group so Ctrl+C in our console doesn't ambiguously
        # signal the child; taskkill /T handles the whole tree regardless.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # killpg needs its own group

    try:
        proc = subprocess.Popen(
            popen_args,
            shell=use_shell,
            cwd=perm.workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merged: live ordering stays sane
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
    except OSError as exc:
        return ToolResult(False, f"Could not run command: {exc}")

    lines: "queue.Queue[object]" = queue.Queue()
    thread = threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True)
    thread.start()

    chunks: list[str] = []
    collected = 0
    deadline = time.monotonic() + timeout_s
    eof = False
    try:
        while not eof:
            if time.monotonic() > deadline:
                _kill_tree(proc)
                partial = "".join(chunks).rstrip()
                tail = f"\nOutput before timeout:\n{partial}" if partial else ""
                return ToolResult(
                    False, f"Command timed out after {timeout_s}s: {command}{tail}"
                )
            try:
                item = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is _EOF:
                eof = True
                continue
            line = str(item)
            if collected < MAX_OUTPUT_CHARS:
                chunks.append(line)
                collected += len(line)
            if on_line is not None:
                try:
                    on_line(line.rstrip("\r\n"))
                except Exception:
                    pass  # a UI echo bug must never kill the command
    except KeyboardInterrupt:
        # Ctrl+C cancels THIS command, not the agent turn.
        _kill_tree(proc)
        partial = "".join(chunks).rstrip()
        tail = f"\nOutput before cancel:\n{partial}" if partial else ""
        return ToolResult(False, f"Command cancelled by user (Ctrl+C): {command}{tail}")

    proc.wait()
    body = "".join(chunks).rstrip() or "(no output)"

    # Make exit code failure explicit
    success = proc.returncode == 0
    status = "✓ Success" if success else f"✗ FAILED (exit code {proc.returncode})"

    return ToolResult(success, f"{status}\n{body}")


@register(
    "run_command",
    "Run a shell command in the workspace; output streams live to the user.",
    {
        "command": "the shell command to run",
        "timeout": "(optional) seconds before the command is killed (default 60)",
        "shell": "(optional) cmd, powershell, or bash (default: system shell)",
    },
    mutates=True,
    types={"timeout": "integer"},
)
def _run_command(perm: "PermissionManager", args: dict[str, Any]) -> ToolResult:
    command = str(args["command"]).strip()
    if not command:
        return ToolResult(False, "Command is empty.")
    timeout_s = int_arg(args, "timeout", _DEFAULT_TIMEOUT_S, 1, _MAX_TIMEOUT_S)
    perm.check_execute(command)
    perm.confirm_action(CATEGORY_SHELL, command)
    return run_command(perm, command, timeout_s, shell=str(args.get("shell", "")))
