"""/theme — interactive theme picker with live preview.

Arrow keys switch themes instantly: the on-highlight hook applies each
palette to the console as the cursor moves, and a sample block above the
picker shows the new colours immediately. Esc restores the original theme;
Enter persists the choice to config.
"""

from __future__ import annotations

from rich.text import Text

from ..config import save_config
from ..ui.selector import Option, select
from ..ui.theme import PALETTES, active_theme_name
from . import CommandContext, CommandResult, command


def _preview(ui) -> None:
    """Print a small sample block in the (just applied) active theme."""
    ui.blank()
    sample = Text()
    sample.append("Seed Code", style="seed.primary")
    sample.append("  Plant ideas. Grow code.\n", style="seed.accent")
    sample.append("Regular text, ", style="seed.text")
    sample.append("dimmed detail, ", style="seed.dim")
    sample.append("warning, ", style="seed.warning")
    sample.append("error.", style="seed.error")
    ui.panel(sample, title="Preview")


def pick_theme(ui, config) -> None:
    """Run the live-preview theme picker and persist the selection."""
    original = active_theme_name()

    def apply_live(option: Option) -> None:
        ui.apply_theme(str(option.value))

    options = [
        Option(p.label, p.id, detail=p.description)
        for p in PALETTES.values()
    ]
    chosen = select(
        options,
        title="Theme",
        hint="↑↓ preview live   Enter apply   Esc keep current",
        initial=original,
        on_highlight=apply_live,
        searchable=True,
    )
    if chosen is None:
        ui.apply_theme(original)
        ui.dim("Theme unchanged.")
        return
    ui.apply_theme(str(chosen))
    config.theme = str(chosen)
    save_config(config)
    _preview(ui)
    ui.success(f"Theme set to {PALETTES[str(chosen)].label}.")


@command("theme", "Pick a colour theme (live preview)")
def _theme(ctx: CommandContext, arg: str) -> CommandResult:
    name = arg.strip().lower()
    if name:
        if name not in PALETTES:
            known = ", ".join(PALETTES)
            ctx.ui.warning(f"Unknown theme '{name}'. Available: {known}")
            return CommandResult()
        ctx.ui.apply_theme(name)
        ctx.config.theme = name
        save_config(ctx.config)
        ctx.ui.success(f"Theme set to {PALETTES[name].label}.")
        return CommandResult()
    pick_theme(ctx.ui, ctx.config)
    return CommandResult()
