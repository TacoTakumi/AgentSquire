"""Interactive install front-end (REQ-07, REQ-08, REQ-09, REQ-16).

This is the ONLY module that imports ``questionary`` (and, transitively,
``prompt_toolkit``). It gathers an install *plan* — a list of
``(harness, scope)`` targets — by prompting the user, then hands that plan to
the shared, prompt_toolkit-free executor in :mod:`agentsquire.cli`. The plan
resolution, the executor, and the verbs import nothing from here, so a
non-interactive or CI invocation never pulls a terminal-UI library in.

The flow is, in order (REQ-07): a checkbox multi-select of exactly the detected
harnesses, then for each selected harness a scope select offering only the
scopes that harness supports (REQ-08), then a confirm summary that lists every
``(harness, scope)`` pair before any filesystem write (REQ-09).
"""

from __future__ import annotations

import questionary

from agentsquire.cli import HarnessTarget, RemovableSkill
from agentsquire.harnesses import HarnessBackend

# Friendly labels for the scope keys; the label carries both the harness term
# and the scope value so the choice reads well and stays greppable.
_SCOPE_LABELS = {"user": "Global (user)", "project": "Local (project)"}


def _confirm_summary(plan: list[HarnessTarget]) -> str:
    """The confirm prompt text: one line per (harness, scope) pair (REQ-09)."""
    lines = ["Install skills into:"]
    lines += [f"  - {target.backend.name} ({target.scope})" for target in plan]
    lines.append("Proceed?")
    return "\n".join(lines)


def gather_install_plan(
    backends: list[HarnessBackend], *, default_scope: str = "user"
) -> list[HarnessTarget] | None:
    """Prompt for an install plan over the ``backends`` detected harnesses.

    Returns the gathered plan (a non-empty list of :class:`HarnessTarget`) once
    the user confirms; an empty list when there is nothing to do (no harness
    selected, or the confirm was declined) — a clean no-op; or ``None`` when the
    user cancelled a prompt (Ctrl-C/ESC makes ``questionary`` return ``None``) —
    an abort. The caller maps those three outcomes to exit codes and notices;
    this function only gathers and never writes.
    """
    chosen = questionary.checkbox(
        "Install skills into which harnesses?",
        choices=[questionary.Choice(title=b.name, value=b.name) for b in backends],
    ).ask()
    if chosen is None:
        return None  # cancelled at the checkbox
    if not chosen:
        return []  # nothing selected — a clean no-op

    by_name = {backend.name: backend for backend in backends}
    plan: list[HarnessTarget] = []
    for name in chosen:
        backend = by_name[name]
        supported = backend.supported_scopes()
        scope = questionary.select(
            f"Scope for {backend.name}?",
            choices=[
                questionary.Choice(title=_SCOPE_LABELS[scope], value=scope)
                for scope in supported
            ],
            default=default_scope if default_scope in supported else None,
        ).ask()
        if scope is None:
            return None  # cancelled mid-flow
        plan.append(HarnessTarget(backend=backend, scope=scope, explicit=True))

    answer = questionary.confirm(_confirm_summary(plan)).ask()
    if answer is None:
        return None  # cancelled at the confirm
    if not answer:
        return []  # declined — a clean no-op
    return plan


def _entry_label(entry: RemovableSkill) -> str:
    """One picker row / summary line for an installed-and-ours skill."""
    return f"{entry.name} ({entry.backend.name}/{entry.scope})"


def _uninstall_summary(entries: list[RemovableSkill]) -> str:
    """The destructive confirm text: one line per skill to be removed."""
    lines = ["Remove these skills:"]
    lines += [f"  - {_entry_label(entry)}" for entry in entries]
    lines.append("This deletes the installed directories. Proceed?")
    return "\n".join(lines)


def gather_uninstall_plan(
    entries: list[RemovableSkill], *, assume_yes: bool = False
) -> list[RemovableSkill] | None:
    """Prompt for which installed-and-ours skills to remove (REQ-22, REQ-23).

    ``entries`` is the enumerated installed-and-ours set. Returns the selected
    subset once confirmed (a non-empty list); an empty list when nothing was
    selected or the confirm was declined (a clean no-op); or ``None`` when the
    user cancelled a prompt (an abort). With ``assume_yes`` the destructive
    confirm is pre-answered and never shown. Only gathers — never deletes.
    """
    chosen = questionary.checkbox(
        "Uninstall which skills?",
        choices=[
            questionary.Choice(title=_entry_label(entry), value=index)
            for index, entry in enumerate(entries)
        ],
    ).ask()
    if chosen is None:
        return None  # cancelled at the checkbox
    if not chosen:
        return []  # nothing selected — a clean no-op

    selection = [entries[index] for index in chosen]
    if assume_yes:
        return selection  # -y pre-answers the destructive confirm
    answer = questionary.confirm(_uninstall_summary(selection)).ask()
    if answer is None:
        return None  # cancelled at the confirm
    if not answer:
        return []  # declined — a clean no-op
    return selection
