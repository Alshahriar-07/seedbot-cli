"""Tool contracts and registry for agent mode.

A tool is a named action with a JSON-friendly argument schema and a runner.
The registry is the single source of truth for what the agent can do; the
system prompt shown to the model is generated from it (:func:`tool_manifest`),
so the documentation the model sees can never drift from the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .permissions import PermissionManager

# Output larger than this is truncated before it re-enters the conversation,
# keeping a single tool call from blowing the model's context window.
MAX_OUTPUT_CHARS = 12_000


class ToolError(Exception):
    """A tool could not complete; the message is fed back to the model."""


def int_arg(args: dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    """Coerce an integer argument, clamped to [lo, hi].

    Models sometimes send numbers as strings or send junk; a friendly
    :class:`ToolError` beats the raw ``ValueError`` the generic crash guard
    would otherwise surface.
    """
    raw = args.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ToolError(f"Argument '{name}' must be a whole number, got {raw!r}.") from None
    return max(lo, min(value, hi))


@dataclass(slots=True)
class ToolResult:
    """Outcome of one tool execution, fed back into the conversation."""

    ok: bool
    output: str

    def for_model(self) -> str:
        """Result text as the model sees it, truncated to a safe size."""
        text = self.output if self.output.strip() else "(no output)"
        if len(text) > MAX_OUTPUT_CHARS:
            omitted = len(text) - MAX_OUTPUT_CHARS
            text = text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {omitted} chars]"
        status = "OK" if self.ok else "ERROR"
        return f"[{status}] {text}"


Runner = Callable[["PermissionManager", dict[str, Any]], ToolResult]


@dataclass(slots=True)
class Tool:
    """One agent-callable action."""

    name: str
    description: str
    # arg name -> one-line description; "(optional)" marks optional args.
    args: dict[str, str]
    # True when the tool changes files or system state (drives permissions).
    mutates: bool
    runner: Runner
    # Which engine the tool belongs to: "core" (files/search/git/shell) or
    # "desktop" (the Computer Engine). Drives manifest filtering so plain
    # agent mode never advertises desktop tools.
    group: str = "core"
    # arg name -> JSON-schema type for non-string args ("integer",
    # "boolean", ...). Unlisted args are strings. Drives native tool schemas.
    types: dict[str, str] = field(default_factory=dict)

    def run(self, permissions: "PermissionManager", args: dict[str, Any]) -> ToolResult:
        missing = [
            name
            for name, desc in self.args.items()
            if "(optional)" not in desc and name not in args
        ]
        if missing:
            raise ToolError(
                f"Tool '{self.name}' is missing required argument(s): {', '.join(missing)}."
            )
        return self.runner(permissions, args)


TOOL_REGISTRY: dict[str, Tool] = {}


def register(
    name: str,
    description: str,
    args: dict[str, str],
    *,
    mutates: bool,
    group: str = "core",
    types: dict[str, str] | None = None,
) -> Callable[[Runner], Runner]:
    """Decorator registering a runner in the tool table."""

    def wrap(runner: Runner) -> Runner:
        TOOL_REGISTRY[name] = Tool(
            name=name,
            description=description,
            args=args,
            mutates=mutates,
            runner=runner,
            group=group,
            types=types or {},
        )
        return runner

    return wrap


def get_tool(name: str) -> Tool:
    tool = TOOL_REGISTRY.get((name or "").strip().lower())
    if tool is None:
        known = ", ".join(sorted(TOOL_REGISTRY))
        raise ToolError(f"Unknown tool '{name}'. Available tools: {known}.")
    return tool


def tool_manifest(groups: tuple[str, ...] = ("core",)) -> str:
    """Tool documentation injected into the agent system prompt.

    Only tools in ``groups`` are listed, so what the model is told matches
    what the session actually allows (e.g. desktop tools only appear when
    desktop mode is on).
    """
    lines = []
    for tool in sorted(TOOL_REGISTRY.values(), key=lambda t: t.name):
        if tool.group not in groups:
            continue
        arg_desc = ", ".join(f'"{a}": {d}' for a, d in tool.args.items()) or "none"
        lines.append(f"- {tool.name}: {tool.description}\n  args: {arg_desc}")
    return "\n".join(lines)


def tool_specs(groups: tuple[str, ...] = ("core",)) -> list[dict[str, Any]]:
    """Neutral name/description/parameters specs for native tool calling.

    Generated from the same registry as :func:`tool_manifest`, so the schema
    a provider sends can never drift from the implementation. Each entry is
    ``{"name", "description", "parameters"}`` with ``parameters`` a
    JSON-schema object; args whose description lacks "(optional)" are
    required.
    """
    specs: list[dict[str, Any]] = []
    for tool in sorted(TOOL_REGISTRY.values(), key=lambda t: t.name):
        if tool.group not in groups:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for arg, desc in tool.args.items():
            properties[arg] = {
                "type": tool.types.get(arg, "string"),
                "description": desc,
            }
            if "(optional)" not in desc:
                required.append(arg)
        specs.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return specs
