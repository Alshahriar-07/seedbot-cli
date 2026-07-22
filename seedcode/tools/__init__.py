"""Tool engine for Seed Code agent mode.

Tools are the actions the agent may take on the user's machine: reading and
writing files, searching, running commands, and using git. Every tool is
registered in a table (mirroring the slash-command registry) and every
execution passes through the :class:`~seedcode.tools.permissions.PermissionManager`
first, so what the agent may touch is decided in exactly one place.
"""

from __future__ import annotations

from .base import Tool, ToolError, ToolResult, TOOL_REGISTRY, get_tool, tool_manifest
from .permissions import (
    PermissionError_,
    PermissionLevel,
    PermissionManager,
    PermissionMode,
)

# Import tool modules for their registration side effects (same pattern as
# seedcode.commands): each module's @register calls populate TOOL_REGISTRY.
from . import desktop, filesystem, git, patch, search, terminal  # noqa: E402,F401

__all__ = [
    "PermissionError_",
    "PermissionLevel",
    "PermissionManager",
    "PermissionMode",
    "TOOL_REGISTRY",
    "Tool",
    "ToolError",
    "ToolResult",
    "get_tool",
    "tool_manifest",
]
