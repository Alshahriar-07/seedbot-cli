"""The built-in skill catalog.

Concrete, deterministic skills registered into ``skills.REGISTRY``. Each is a
real procedure over the :class:`ComputerController` primitives — launching apps,
driving the browser, creating projects, editor/clipboard/git actions — with a
declared permission level and an ``expected`` outcome for the verifier. No
placeholders, no AI calls.

Importing this module has the side effect of populating the registry; the
Computer Engine imports it once at startup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..tools.permissions import PermissionLevel, CATEGORY_SHELL
from .skills import Outcome, SkillContext, SkillError, skill


def _req(params: dict[str, Any], key: str) -> str:
    val = str(params.get(key, "")).strip()
    if not val:
        raise SkillError(f"skill requires a '{key}' parameter")
    return val


# --- application launching --------------------------------------------------

@skill("launch_app", "Open or focus a desktop application by name or path.",
       PermissionLevel.DESKTOP, {"target": "app name, e.g. 'notepad' or a path"})
def launch_app(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    target = _req(params, "target")
    # Already open? Focus it instead of spawning a duplicate.
    for w in ctx.controller.list_windows():
        if target.lower() in w.title.lower():
            ctx.controller.focus_window(w.title)
            ctx.state.note_focus(w.title)
            return Outcome(f"focused existing {w.title}", {"window": target},
                           window_title=w.title, app_target=target)
    ctx.controller.open_app(target)
    ctx.state.record_action(f"launched {target}")
    ctx.state.note_focus(target)
    return Outcome(f"launched {target}", {"window": target},
                   window_title=target, app_target=target)


@skill("focus_app", "Bring an already-open application to the foreground.",
       PermissionLevel.DESKTOP, {"target": "part of the window title"})
def focus_app(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    target = _req(params, "target")
    win = ctx.controller.focus_window(target)
    title = getattr(win, "title", target)
    ctx.state.note_focus(title)
    return Outcome(f"focused {title}", {"window": target}, window_title=title)


@skill("close_app", "Close an application window.",
       PermissionLevel.DESKTOP, {"target": "part of the window title"})
def close_app(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    target = _req(params, "target")
    ctx.controller.close_app(target)
    ctx.state.record_action(f"closed {target}")
    return Outcome(f"closed {target}", {"window_gone": target})


@skill("launch_vscode", "Open Visual Studio Code, optionally on a folder.",
       PermissionLevel.DESKTOP, {"path": "(optional) folder to open"})
def launch_vscode(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    path = str(params.get("path", "")).strip()
    target = f'code "{path}"' if path else "code"
    ctx.controller.open_app(target)
    ctx.state.note_focus("Visual Studio Code")
    return Outcome(f"opened VS Code{f' on {path}' if path else ''}",
                   {"window": "Visual Studio Code"},
                   window_title="Visual Studio Code", app_target="code")


@skill("launch_terminal", "Open a terminal window.", PermissionLevel.DESKTOP)
def launch_terminal(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    # Windows Terminal if present, else the classic console.
    target = "wt" if os.name == "nt" else "x-terminal-emulator"
    try:
        ctx.controller.open_app(target)
    except Exception:
        ctx.controller.open_app("cmd" if os.name == "nt" else "xterm")
    ctx.state.note_focus("Terminal")
    return Outcome("opened a terminal", {"window": "Terminal"}, app_target=target)


# --- browser ----------------------------------------------------------------

@skill("launch_browser", "Open a web browser at a URL (defaults to a blank tab).",
       PermissionLevel.DESKTOP, {"url": "(optional) URL to open"})
def launch_browser(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    url = str(params.get("url", "")).strip() or "about:blank"
    if not url.startswith(("http://", "https://", "about:")):
        url = "https://" + url
    ctx.controller.browser_navigate(url)
    ctx.state.record_action(f"opened browser at {url}")
    return Outcome(f"opened browser at {url}", {"browser_url": url.split("//")[-1][:20]})


@skill("google_search", "Search Google for a query in the browser.",
       PermissionLevel.DESKTOP, {"query": "search terms"})
def google_search(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    query = _req(params, "query")
    from urllib.parse import quote_plus

    url = f"https://www.google.com/search?q={quote_plus(query)}"
    ctx.controller.browser_navigate(url)
    ctx.state.record_action(f"searched Google for {query}")
    return Outcome(f"searched Google for '{query}'", {"browser_url": "google.com"})


@skill("youtube_search", "Search YouTube for a query in the browser.",
       PermissionLevel.DESKTOP, {"query": "search terms"})
def youtube_search(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    query = _req(params, "query")
    from urllib.parse import quote_plus

    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
    ctx.controller.browser_navigate(url)
    ctx.state.record_action(f"searched YouTube for {query}")
    return Outcome(f"searched YouTube for '{query}'", {"browser_url": "youtube.com"})


# --- editor / clipboard -----------------------------------------------------

@skill("save_current_file", "Save the file in the focused editor (Ctrl+S).",
       PermissionLevel.DESKTOP)
def save_current_file(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    ctx.controller.hotkey(["ctrl", "s"])
    ctx.state.record_action("saved current file")
    return Outcome("sent save (Ctrl+S) to the focused window")


@skill("copy_selection", "Copy the current selection to the clipboard.",
       PermissionLevel.DESKTOP)
def copy_selection(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    ctx.controller.hotkey(["ctrl", "c"])
    ctx.state.record_action("copied selection")
    return Outcome("copied selection to clipboard")


@skill("paste_clipboard", "Paste the clipboard into the focused window.",
       PermissionLevel.DESKTOP)
def paste_clipboard(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    ctx.controller.hotkey(["ctrl", "v"])
    ctx.state.record_action("pasted clipboard")
    return Outcome("pasted clipboard into the focused window")


# --- filesystem / projects (workspace level) --------------------------------

@skill("create_python_project", "Scaffold a Python project folder with main.py and a venv-ready layout.",
       PermissionLevel.WORKSPACE, {"name": "project folder name", "path": "(optional) parent dir"})
def create_python_project(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    name = _req(params, "name")
    parent = ctx.permissions.resolve(str(params.get("path", ".")))
    root = parent / name
    ctx.permissions.check_write(root)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text(
        'def main() -> None:\n    print("Hello from ' + name + '")\n\n\n'
        'if __name__ == "__main__":\n    main()\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    (root / "requirements.txt").write_text("", encoding="utf-8")
    ctx.state.record_action(f"created python project {name}")
    return Outcome(f"created Python project at {root}", {"file_exists": str(root / "src" / "main.py")})


# --- terminal / commands (require confirmation) -----------------------------

@skill("run_python", "Run a Python script with the system interpreter.",
       PermissionLevel.WORKSPACE, {"script": "path to the .py file"}, sensitive=True)
def run_python(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    script = _req(params, "script")
    path = ctx.permissions.resolve(script)
    ctx.permissions.check_execute(f"python {path}")
    ctx.permissions.confirm_action(CATEGORY_SHELL, f"python {path}")
    out = _run_command(["python", str(path)], cwd=ctx.permissions.workspace, ctx=ctx)
    return Outcome(f"ran {path}\n{out}")


@skill("run_node", "Run a JavaScript file with Node.js.",
       PermissionLevel.WORKSPACE, {"script": "path to the .js file"}, sensitive=True)
def run_node(ctx: SkillContext, params: dict[str, Any]) -> Outcome:
    script = _req(params, "script")
    path = ctx.permissions.resolve(script)
    ctx.permissions.check_execute(f"node {path}")
    ctx.permissions.confirm_action(CATEGORY_SHELL, f"node {path}")
    out = _run_command(["node", str(path)], cwd=ctx.permissions.workspace, ctx=ctx)
    return Outcome(f"ran {path}\n{out}")


def _run_command(argv: list[str], *, cwd: Path, ctx: SkillContext) -> str:
    import subprocess

    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=120
        )
    except FileNotFoundError:
        raise SkillError(f"'{argv[0]}' is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise SkillError(f"'{' '.join(argv)}' timed out after 120s")
    output = (proc.stdout or "") + (proc.stderr or "")
    if ctx.permissions.on_output and output:
        for line in output.splitlines():
            ctx.permissions.on_output(line)
    return output.strip()[:4000] or f"(exit {proc.returncode}, no output)"
