"""Vision driver: the agent's eyes on the desktop.

The primary source of truth is the Windows UI Automation tree — real
elements (buttons, inputs, menus, dialogs) with exact coordinates, described
as text so EVERY provider can use desktop mode, not just multimodal ones.
Screenshots complement it for image-capable models, and OCR (pytesseract,
if the user happens to have it) is a best-effort fallback for windows that
expose no automation tree (games, some custom-drawn apps).
"""

from __future__ import annotations

from dataclasses import dataclass

# Bound the tree walk: deep UIA trees (browsers) can hold thousands of nodes.
MAX_ELEMENTS = 150
MAX_DEPTH = 12

# Control types worth reporting to the model (interactive or informative).
_INTERESTING_TYPES = {
    "ButtonControl": "button",
    "EditControl": "input",
    "ComboBoxControl": "combobox",
    "CheckBoxControl": "checkbox",
    "RadioButtonControl": "radio",
    "HyperlinkControl": "link",
    "MenuItemControl": "menuitem",
    "MenuControl": "menu",
    "TabItemControl": "tab",
    "ListItemControl": "listitem",
    "TextControl": "text",
    "DocumentControl": "document",
    "WindowControl": "dialog",
    "TitleBarControl": "titlebar",
    "ToolBarControl": "toolbar",
    "TreeItemControl": "treeitem",
    "SliderControl": "slider",
}


@dataclass(slots=True)
class UIElement:
    """One visible UI element with its clickable center point."""

    role: str
    name: str
    x: int  # center
    y: int  # center
    width: int
    height: int
    enabled: bool

    def describe(self) -> str:
        state = "" if self.enabled else " (disabled)"
        name = self.name[:80] if self.name else "(unnamed)"
        return f'{self.role} "{name}" at ({self.x}, {self.y}){state}'


def snapshot(window_title: str | None = None) -> tuple[str, list[UIElement]]:
    """UI-tree snapshot of the active (or named) window.

    Returns (window title, elements). Raises ValueError when the target
    window cannot be found.
    """
    import uiautomation as auto

    if window_title:
        root = auto.WindowControl(searchDepth=1, SubName=window_title)
        if not root.Exists(maxSearchSeconds=2):
            raise ValueError(f"No window found matching '{window_title}'.")
    else:
        root = auto.GetForegroundControl()
        if root is None:
            raise ValueError("No foreground window to inspect.")
        top = root.GetTopLevelControl()
        if top is not None:
            root = top

    elements: list[UIElement] = []
    _walk(root, elements, depth=0)
    return (root.Name or "(untitled window)", elements)


def _walk(control, out: list[UIElement], depth: int) -> None:
    if len(out) >= MAX_ELEMENTS or depth > MAX_DEPTH:
        return
    for child in control.GetChildren():
        if len(out) >= MAX_ELEMENTS:
            return
        try:
            type_name = child.ControlTypeName
            role = _INTERESTING_TYPES.get(type_name)
            rect = child.BoundingRectangle
            visible = rect is not None and rect.width() > 0 and rect.height() > 0
            if role is not None and visible:
                name = (child.Name or "").strip()
                # Skip anonymous static text: it adds noise, not targets.
                if not (role == "text" and not name):
                    out.append(
                        UIElement(
                            role=role,
                            name=name,
                            x=rect.left + rect.width() // 2,
                            y=rect.top + rect.height() // 2,
                            width=rect.width(),
                            height=rect.height(),
                            enabled=bool(child.IsEnabled),
                        )
                    )
        except Exception:
            # A single flaky COM element must not kill the whole snapshot.
            continue
        _walk(child, out, depth + 1)


def describe_snapshot(title: str, elements: list[UIElement]) -> str:
    """Model-facing text rendering of a snapshot."""
    if not elements:
        return (
            f'Window "{title}" exposes no UI Automation elements '
            "(custom-drawn app?). Use desktop_screenshot and OCR/vision instead."
        )
    lines = [f'Window "{title}" — {len(elements)} elements:']
    lines += [f"  - {el.describe()}" for el in elements]
    if len(elements) >= MAX_ELEMENTS:
        lines.append(f"  ... (truncated at {MAX_ELEMENTS} elements)")
    return "\n".join(lines)


def element_at(x: int, y: int) -> str:
    """Describe the UI element under a point (used to verify actions)."""
    try:
        import uiautomation as auto

        control = auto.ControlFromPoint(x, y)
        if control is None:
            return "nothing"
        role = _INTERESTING_TYPES.get(control.ControlTypeName, control.ControlTypeName)
        name = (control.Name or "").strip()[:80]
        return f'{role} "{name or "(unnamed)"}"'
    except Exception:
        return "unknown"


def ocr_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pytesseract") is not None


def ocr_screenshot(image_path) -> str:
    """Best-effort OCR of a screenshot (only when pytesseract is installed)."""
    if not ocr_available():
        return (
            "OCR is not installed. The UI Automation snapshot (desktop_see) "
            "is the primary way to read the screen."
        )
    try:
        import pytesseract
        from PIL import Image

        with Image.open(image_path) as img:
            text = pytesseract.image_to_string(img)
        return text.strip() or "(no text recognised)"
    except Exception as exc:
        return f"OCR failed: {exc}"


def ocr_locate(image_path, phrase: str) -> tuple[int, int, int, int] | None:
    """Find ``phrase`` on a screenshot; return its (left, top, width, height).

    Used by the element resolver as the fallback path for windows that expose
    no UI Automation tree. Matches a run of consecutive OCR words whose joined
    text contains the phrase (case-insensitive), and returns the bounding box
    that spans them. Returns None when the phrase is not found or OCR is
    unavailable — the resolver then reports the element as unresolvable.
    """
    if not ocr_available():
        return None
    try:
        import pytesseract
        from PIL import Image

        want = " ".join((phrase or "").lower().split())
        if not want:
            return None
        with Image.open(image_path) as img:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception:
        return None

    words = data.get("text", [])
    n = len(words)
    # Slide a window of up to the phrase's word-count over the OCR words and
    # accept the first run whose joined text contains the phrase.
    span = max(1, len(want.split()))
    for i in range(n):
        for length in range(1, span + 1):
            if i + length > n:
                break
            chunk = " ".join(w for w in words[i : i + length] if w).lower().strip()
            if chunk and want in chunk:
                lefts = [data["left"][k] for k in range(i, i + length)]
                tops = [data["top"][k] for k in range(i, i + length)]
                rights = [data["left"][k] + data["width"][k] for k in range(i, i + length)]
                bottoms = [data["top"][k] + data["height"][k] for k in range(i, i + length)]
                left, top = min(lefts), min(tops)
                return (left, top, max(rights) - left, max(bottoms) - top)
    return None
