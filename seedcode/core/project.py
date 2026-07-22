"""Project awareness: detect what kind of project the workspace holds.

Runs once at agent-engine construction and feeds a short summary into the
system prompt, so the model starts oriented (project type, git branch,
top-level layout) without spending tool calls on discovery. Detection is
marker-file based and touches only the top level — no recursive walk, no
subprocesses — so construction stays instant even in huge repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Marker file/dir -> human-readable project kind. Checked in order; every
# match is reported (a repo can be several things at once).
_MARKERS: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "Python (pyproject.toml)"),
    ("setup.py", "Python (setup.py)"),
    ("package.json", "Node.js (package.json)"),
    ("Cargo.toml", "Rust (Cargo.toml)"),
    ("go.mod", "Go (go.mod)"),
    ("pom.xml", "Java (Maven)"),
    ("build.gradle", "Java/Kotlin (Gradle)"),
    ("build.gradle.kts", "Kotlin (Gradle)"),
    ("CMakeLists.txt", "C/C++ (CMake)"),
    ("Gemfile", "Ruby (Gemfile)"),
    ("composer.json", "PHP (Composer)"),
)

# Top-level entries that add noise, not orientation.
_LISTING_SKIP = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
}
_MAX_LISTING = 40


@dataclass(slots=True)
class ProjectInfo:
    """What was detected about the workspace."""

    kinds: list[str]
    summary: str


def _git_branch(workspace: Path) -> str:
    """Current branch read straight from .git/HEAD (no subprocess)."""
    head = workspace / ".git" / "HEAD"
    try:
        content = head.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if content.startswith("ref: refs/heads/"):
        return content[len("ref: refs/heads/"):]
    return content[:12] if content else ""  # detached HEAD: short hash


def detect_project(workspace: Path) -> ProjectInfo:
    """Detect project kinds and build the system-prompt summary block."""
    kinds: list[str] = []

    if (workspace / ".git").is_dir():
        branch = _git_branch(workspace)
        kinds.append(f"Git repository (branch: {branch})" if branch else "Git repository")

    for marker, kind in _MARKERS:
        if (workspace / marker).is_file():
            kinds.append(kind)

    if any(workspace.glob("*.csproj")):
        kinds.append("C# (.csproj)")

    lines: list[str] = []
    if kinds:
        lines.append("Detected: " + ", ".join(kinds))
    lines.append("Top-level entries:")
    try:
        entries = sorted(
            workspace.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
    except OSError:
        entries = []
    shown = 0
    for entry in entries:
        if entry.name in _LISTING_SKIP or entry.name.startswith("."):
            continue
        if shown >= _MAX_LISTING:
            lines.append("  ... (more entries; use list_dir/project_index)")
            break
        lines.append(f"  {entry.name}{'/' if entry.is_dir() else ''}")
        shown += 1
    if shown == 0:
        lines.append("  (empty workspace)")

    return ProjectInfo(kinds=kinds, summary="\n".join(lines))
