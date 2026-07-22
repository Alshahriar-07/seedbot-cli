"""Nested navigation trees: settings screens with breadcrumbs.

A :class:`TreeNode` is either a branch (children) or a leaf (an action
callback). :func:`navigate` walks the tree with the interactive selector,
showing a ``Settings › Providers › FreeModel Claude`` breadcrumb at every
level. Esc goes up one level; Esc at the root exits. Leaf callbacks return
True to stay on the current level (so a value edit refreshes in place) or
False/None to exit the whole tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from .selector import Option, select


@dataclass
class TreeNode:
    """One navigable node.

    Branches set ``children`` (static) or ``build`` (computed per visit so
    live values stay fresh). Leaves set ``action``. ``status`` is the dimmed
    current-value column shown next to the label.
    """

    label: str
    children: Sequence["TreeNode"] = field(default_factory=tuple)
    build: Callable[[], Sequence["TreeNode"]] | None = None
    action: Callable[[], object] | None = None
    status: str = ""
    status_fn: Callable[[], str] | None = None
    badge: str = ""

    def resolve_children(self) -> Sequence["TreeNode"]:
        if self.build is not None:
            return self.build()
        return self.children

    def resolve_status(self) -> str:
        if self.status_fn is not None:
            try:
                return self.status_fn()
            except Exception:
                return ""
        return self.status


def navigate(root: TreeNode, *, breadcrumbs: Sequence[str] = ()) -> None:
    """Walk ``root`` interactively until the user backs out of the top level."""
    trail = list(breadcrumbs) or [root.label]
    _navigate_level(root, trail)


def _navigate_level(node: TreeNode, trail: list[str]) -> bool:
    """Show one level; returns False when the whole tree should exit."""
    last = None
    while True:
        children = list(node.resolve_children())
        if not children:
            return True
        options = [
            Option(
                child.label,
                value=i,
                columns=(child.resolve_status(),) if child.resolve_status() else (),
                badge=child.badge,
            )
            for i, child in enumerate(children)
        ]
        chosen = select(
            options,
            breadcrumbs=trail,
            hint="↑↓ move   Enter open   Esc back",
            initial=last,
        )
        if chosen is None:
            return True  # Esc: up one level
        last = chosen
        child = children[int(chosen)]
        if child.action is not None:
            try:
                keep = child.action()
            except (KeyboardInterrupt, EOFError):
                keep = True
            if keep is False:
                return False
            continue
        if not _navigate_level(child, trail + [child.label]):
            return False
