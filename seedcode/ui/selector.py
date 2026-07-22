"""The interactive list selector — the core Seed Code UI component.

One keyboard-first widget replaces every numeric menu in the app:

* ``↑ ↓`` (and ``Tab``/``Shift+Tab``) move, ``Enter`` confirms, ``Esc`` and
  ``Ctrl+C`` cancel — the user is never trapped.
* ``Home``/``End``/``PageUp``/``PageDown`` jump; long lists scroll inside a
  fixed viewport so only changed rows are redrawn (prompt_toolkit renders
  differentially — no flicker, no full-screen repaints).
* Typing filters instantly with fuzzy matching (``cld`` → Claude,
  ``gpt55`` → GPT-5.5); ``Backspace`` restores; ``Ctrl+L`` clears the query.
* Items can carry status badges, extra columns, and group headers.
* Mouse (where the terminal supports it): click moves the cursor, clicking
  the highlighted row confirms, the scroll wheel scrolls.
* ``Delete`` can be wired to remove an entry (history browser).
* An ``on_highlight`` hook fires on every cursor move (live theme preview).

Non-interactive streams (pipes, tests, dumb terminals) fall back to a plain
typed prompt matched with the same fuzzy rules — never a numbered list.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import DynamicStyle

from .badges import badge_fragment
from .fuzzy import FuzzyResult, fuzzy_match
from .theme import pt_style

# Marker used for the highlighted row (the Seed pointer).
POINTER = "❯"  # ❯
_PAGE = 10


@dataclass(slots=True)
class Option:
    """One selectable entry.

    ``columns`` are extra aligned display columns (provider selector shows
    status/backend/model there). ``badge`` is a status key from
    :mod:`seedcode.ui.badges`. ``group`` clusters entries under a header.
    ``search_text`` (defaults to the label) is what fuzzy filtering sees.
    """

    label: str
    value: Any = None
    detail: str = ""
    columns: tuple[str, ...] = ()
    badge: str = ""
    group: str = ""
    disabled: bool = False
    search_text: str = ""

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = self.label
        if not self.search_text:
            self.search_text = (
                f"{self.label} {self.detail} {' '.join(self.columns)}".strip()
            )


@dataclass(slots=True)
class _Row:
    """One rendered line: a group header or a selectable option."""

    option: Option | None  # None => group header
    header: str = ""
    match: FuzzyResult | None = None


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


class Selector:
    """Interactive selector application. Use :func:`select` unless you need
    the extra hooks."""

    def __init__(
        self,
        options: Sequence[Option],
        *,
        title: str = "",
        breadcrumbs: Sequence[str] = (),
        placeholder: str = "type to filter",
        hint: str = "",
        initial: Any = None,
        searchable: bool = True,
        on_highlight: Callable[[Option], None] | None = None,
        on_delete: Callable[[Option], bool] | None = None,
        max_rows: int = 12,
    ) -> None:
        self._all = list(options)
        self._title = title
        self._breadcrumbs = list(breadcrumbs)
        self._placeholder = placeholder
        self._hint = hint
        self._searchable = searchable
        self._on_highlight = on_highlight
        self._on_delete = on_delete
        self._max_rows = max_rows
        self._query = ""
        self._rows: list[_Row] = []
        self._cursor = 0  # index into self._rows (always on a selectable row)
        self._offset = 0  # first visible row
        self._widths: tuple[int, ...] = ()
        self._rebuild()
        if initial is not None:
            for i, row in enumerate(self._rows):
                if row.option is not None and row.option.value == initial:
                    self._cursor = i
                    break
        self._scroll_into_view()

    # --- filtering / row model ----------------------------------------------
    def _rebuild(self) -> None:
        """Recompute visible rows for the current query."""
        if self._query:
            scored = []
            for opt in self._all:
                result = fuzzy_match(self._query, opt.search_text)
                if result.matched:
                    scored.append((opt, result))
            scored.sort(key=lambda pair: -pair[1].score)
            self._rows = [_Row(opt, match=m) for opt, m in scored]
        else:
            self._rows = []
            seen_group = ""
            for opt in self._all:
                if opt.group and opt.group != seen_group:
                    self._rows.append(_Row(None, header=opt.group))
                    seen_group = opt.group
                self._rows.append(_Row(opt))
        self._widths = self._column_widths()
        self._cursor = self._first_selectable(0)
        self._offset = 0

    def _column_widths(self) -> tuple[int, ...]:
        opts = [r.option for r in self._rows if r.option is not None]
        if not opts:
            return ()
        label_w = max(len(o.label) for o in opts)
        ncols = max((len(o.columns) for o in opts), default=0)
        col_w = [
            max((len(o.columns[i]) if i < len(o.columns) else 0) for o in opts)
            for i in range(ncols)
        ]
        return (label_w, *col_w)

    def _first_selectable(self, start: int, step: int = 1) -> int:
        i = start
        while 0 <= i < len(self._rows):
            row = self._rows[i]
            if row.option is not None and not row.option.disabled:
                return i
            i += step
        return -1 if not self._rows else max(0, min(start, len(self._rows) - 1))

    def _selectable_indices(self) -> list[int]:
        return [
            i
            for i, r in enumerate(self._rows)
            if r.option is not None and not r.option.disabled
        ]

    @property
    def current(self) -> Option | None:
        if 0 <= self._cursor < len(self._rows):
            return self._rows[self._cursor].option
        return None

    # --- movement -------------------------------------------------------------
    def _move(self, step: int) -> None:
        sel = self._selectable_indices()
        if not sel:
            return
        try:
            pos = sel.index(self._cursor)
        except ValueError:
            pos = 0
        pos = max(0, min(len(sel) - 1, pos + step))
        self._cursor = sel[pos]
        self._scroll_into_view()
        self._fire_highlight()

    def _move_edge(self, end: bool) -> None:
        sel = self._selectable_indices()
        if not sel:
            return
        self._cursor = sel[-1] if end else sel[0]
        self._scroll_into_view()
        self._fire_highlight()

    def _fire_highlight(self) -> None:
        if self._on_highlight is not None and self.current is not None:
            try:
                self._on_highlight(self.current)
            except Exception:
                pass  # a preview hook must never break navigation

    def _viewport(self) -> int:
        return max(3, min(self._max_rows, len(self._rows)))

    def _scroll_into_view(self) -> None:
        height = self._viewport()
        if self._cursor < self._offset:
            self._offset = self._cursor
        elif self._cursor >= self._offset + height:
            self._offset = self._cursor - height + 1
        self._offset = max(0, min(self._offset, max(0, len(self._rows) - height)))

    # --- mouse -----------------------------------------------------------------
    def _mouse_for(self, row_index: int) -> Callable[[MouseEvent], object]:
        def handler(event: MouseEvent) -> object:
            if event.event_type == MouseEventType.SCROLL_UP:
                self._move(-1)
                return None
            if event.event_type == MouseEventType.SCROLL_DOWN:
                self._move(1)
                return None
            if event.event_type == MouseEventType.MOUSE_UP:
                row = self._rows[row_index] if 0 <= row_index < len(self._rows) else None
                if row is None or row.option is None or row.option.disabled:
                    return NotImplemented
                if self._cursor == row_index:
                    # Second click on the highlighted row confirms it.
                    self._app.exit(result=row.option)
                else:
                    self._cursor = row_index
                    self._scroll_into_view()
                    self._fire_highlight()
                return None
            return NotImplemented

        return handler

    # --- rendering ---------------------------------------------------------------
    def _fragments(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        if self._breadcrumbs:
            for i, crumb in enumerate(self._breadcrumbs):
                if i:
                    out.append(("class:sel.breadcrumb", " › "))  # ›
                style = (
                    "class:sel.breadcrumb.here"
                    if i == len(self._breadcrumbs) - 1
                    else "class:sel.breadcrumb"
                )
                out.append((style, crumb))
            out.append(("", "\n"))
        if self._title:
            out.append(("class:sel.title", self._title))
            out.append(("", "\n"))
        if self._searchable:
            out.append(("class:sel.searchlabel", "  ⚲ "))  # ⚲ search glyph
            if self._query:
                out.append(("class:sel.query", self._query))
            else:
                out.append(("class:sel.placeholder", self._placeholder))
            total = len(self._selectable_indices())
            out.append(("class:sel.counter", f"   {total}/{len(self._all)}"))
            out.append(("", "\n"))

        height = self._viewport()
        visible = self._rows[self._offset : self._offset + height]
        if not visible:
            out.append(("class:sel.dim", "  (no matches — Backspace to widen)\n"))
        for k, row in enumerate(visible):
            idx = self._offset + k
            out.extend(self._row_fragments(row, idx))
            out.append(("", "\n"))

        # Scroll indicator for long lists.
        if len(self._rows) > height:
            above, below = self._offset, len(self._rows) - height - self._offset
            marks = []
            if above:
                marks.append(f"↑ {above} more")
            if below:
                marks.append(f"↓ {below} more")
            out.append(("class:sel.scroll", "  " + "   ".join(marks) + "\n"))

        hint = self._hint or "↑↓ move   Enter select   Esc cancel"
        out.append(("class:sel.hint", f"  {hint}"))
        return out

    def _row_fragments(self, row: _Row, idx: int) -> StyleAndTextTuples:
        handler = self._mouse_for(idx)
        if row.option is None:
            return [("class:sel.group", f"  {row.header}", handler)]
        opt = row.option
        selected = idx == self._cursor
        line = "class:sel.cursorline " if selected else ""
        frags: StyleAndTextTuples = []
        pointer = f"{POINTER} " if selected else "  "
        frags.append((f"{line}class:sel.pointer" if selected else line, pointer, handler))
        if opt.group and self._query == "":
            frags.append((line, "  ", handler))

        base = "class:sel.dim" if opt.disabled else "class:sel.text"
        label_w = self._widths[0] if self._widths else len(opt.label)
        frags.extend(
            _highlighted(opt.label, row.match, f"{line}{base}", f"{line}class:sel.match", handler)
        )
        frags.append((line, " " * max(0, label_w - len(opt.label)), handler))
        if opt.badge:
            frags.append((line, "   ", handler))
            style, text = badge_fragment(opt.badge)
            frags.append((f"{line}{style}", text, handler))
        for i, col in enumerate(opt.columns):
            width = self._widths[i + 1] if i + 1 < len(self._widths) else len(col)
            frags.append((f"{line}class:sel.dim", "   " + col.ljust(width), handler))
        if opt.detail:
            frags.append((f"{line}class:sel.dim", f"   {opt.detail}", handler))
        return frags

    # --- application ---------------------------------------------------------------
    def _build_app(self) -> Application:
        kb = KeyBindings()

        @kb.add("up")
        def _(event) -> None:
            self._move(-1)

        @kb.add("down")
        def _(event) -> None:
            self._move(1)

        kb.add("s-tab")(lambda e: self._move(-1))
        kb.add("tab")(lambda e: self._move(1))
        kb.add("left")(lambda e: self._move(-1))
        kb.add("right")(lambda e: self._move(1))
        kb.add("pageup")(lambda e: self._move(-_PAGE))
        kb.add("pagedown")(lambda e: self._move(_PAGE))
        kb.add("home")(lambda e: self._move_edge(False))
        kb.add("end")(lambda e: self._move_edge(True))

        @kb.add("enter")
        def _(event) -> None:
            current = self.current
            if current is not None and not current.disabled:
                event.app.exit(result=current)

        @kb.add("escape", eager=True)
        @kb.add("c-c")
        def _(event) -> None:
            event.app.exit(result=None)

        @kb.add("backspace")
        def _(event) -> None:
            if self._searchable and self._query:
                self._query = self._query[:-1]
                self._rebuild()
                self._fire_highlight()

        @kb.add("c-l")
        def _(event) -> None:
            if self._searchable and self._query:
                self._query = ""
                self._rebuild()
                self._fire_highlight()

        @kb.add("delete")
        def _(event) -> None:
            current = self.current
            if self._on_delete is None or current is None:
                return
            try:
                removed = self._on_delete(current)
            except Exception:
                removed = False
            if removed:
                self._all = [o for o in self._all if o is not current]
                query, self._query = self._query, ""
                self._query = query
                self._rebuild()
                if not self._all:
                    event.app.exit(result=None)

        @kb.add(Keys.Any)
        def _(event) -> None:
            ch = event.data
            if self._searchable and ch and ch.isprintable():
                self._query += ch
                self._rebuild()
                self._fire_highlight()

        window = Window(
            FormattedTextControl(self._fragments, focusable=True, show_cursor=False),
            always_hide_cursor=True,
            wrap_lines=False,
        )
        self._app: Application = Application(
            layout=Layout(window),
            key_bindings=kb,
            # DynamicStyle re-reads the active theme every render, so the
            # theme picker's live preview recolours this very selector.
            style=DynamicStyle(lambda: pt_style()),
            mouse_support=True,
            full_screen=False,
            erase_when_done=True,
        )
        return self._app

    def run(self) -> Option | None:
        if not self._all:
            return None
        try:
            return self._build_app().run()
        except (EOFError, KeyboardInterrupt):
            return None


def _highlighted(
    text: str,
    match: FuzzyResult | None,
    base_style: str,
    match_style: str,
    handler,
) -> StyleAndTextTuples:
    """Split ``text`` into fragments, highlighting fuzzy-matched positions."""
    if match is None or not match.positions:
        return [(base_style, text, handler)]
    marked = set(match.positions)
    frags: StyleAndTextTuples = []
    run, run_marked = "", False
    for i, ch in enumerate(text):
        m = i in marked
        if run and m != run_marked:
            frags.append((match_style if run_marked else base_style, run, handler))
            run = ""
        run += ch
        run_marked = m
    if run:
        frags.append((match_style if run_marked else base_style, run, handler))
    return frags


# --- plain-stream fallback -------------------------------------------------------
def _fallback_select(options: Sequence[Option], title: str) -> Option | None:
    """Typed selection for non-interactive streams: fuzzy text, no numbers."""
    enabled = [o for o in options if not o.disabled]
    if not enabled:
        return None
    if title:
        print(title)
    for opt in enabled:
        extra = f"  {opt.detail}" if opt.detail else ""
        print(f"  {opt.label}{extra}")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    best: tuple[float, Option] | None = None
    for opt in enabled:
        result = fuzzy_match(raw, opt.search_text)
        if result.matched and (best is None or result.score > best[0]):
            best = (result.score, opt)
    return best[1] if best else None


def select(
    options: Sequence[Option],
    *,
    title: str = "",
    breadcrumbs: Sequence[str] = (),
    hint: str = "",
    initial: Any = None,
    searchable: bool = True,
    on_highlight: Callable[[Option], None] | None = None,
    on_delete: Callable[[Option], bool] | None = None,
    max_rows: int = 12,
) -> Any | None:
    """Run the interactive selector and return the chosen option's value.

    Returns ``None`` when cancelled (Esc/Ctrl+C) or when there is nothing to
    choose from. On non-interactive streams a typed fuzzy prompt is used.
    """
    opts = list(options)
    if not opts:
        return None
    if not _interactive():
        chosen = _fallback_select(opts, title)
        return chosen.value if chosen else None
    selector = Selector(
        opts,
        title=title,
        breadcrumbs=breadcrumbs,
        hint=hint,
        initial=initial,
        searchable=searchable,
        on_highlight=on_highlight,
        on_delete=on_delete,
        max_rows=max_rows,
    )
    chosen = selector.run()
    return chosen.value if chosen else None
