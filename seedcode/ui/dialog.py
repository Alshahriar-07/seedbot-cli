"""Interactive dialogs: confirmations and permission prompts.

Replaces every [Y]/[N] text prompt with an arrow-key choice list:

    ❯ Allow Once
      Always Allow
      Deny

Esc/Ctrl+C always mean the safe answer (deny/cancel) — an accidental
cancel can never grant a permission.
"""

from __future__ import annotations

from .selector import Option, select

# Values returned by permission_dialog, aligned with the existing gates.
ALLOW_ONCE = "y"
ALLOW_ALWAYS = "a"
DENY = "n"


def permission_dialog(*, allow_always: bool = True) -> str:
    """Ask Allow Once / Always Allow / Deny; returns 'y', 'a', or 'n'.

    Cancelling (Esc/Ctrl+C) returns 'n' — never an approval.
    """
    options = [Option("Allow Once", ALLOW_ONCE, detail="approve this action only")]
    if allow_always:
        options.append(
            Option("Always Allow", ALLOW_ALWAYS, detail="approve for this session")
        )
    options.append(Option("Deny", DENY, detail="block this action"))
    result = select(
        options,
        searchable=False,
        hint="↑↓ move   Enter confirm   Esc deny",
    )
    return result if result in (ALLOW_ONCE, ALLOW_ALWAYS, DENY) else DENY


def confirm_dialog(
    question: str,
    *,
    yes_label: str = "Yes",
    no_label: str = "No",
    danger: bool = False,
) -> bool:
    """A two-option yes/no dialog; Esc/cancel counts as No.

    ``danger=True`` puts No first so Enter-mashing never destroys anything.
    """
    yes = Option(yes_label, True)
    no = Option(no_label, False)
    options = [no, yes] if danger else [yes, no]
    result = select(
        options,
        title=question,
        searchable=False,
        hint="↑↓ move   Enter confirm   Esc cancel",
    )
    return bool(result)
