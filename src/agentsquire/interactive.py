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

from agentsquire.cli import HarnessTarget
from agentsquire.harnesses import SCOPES, HarnessBackend

# Friendly labels for the scope keys; the label carries both the harness term
# and the scope value so the choice reads well and stays greppable.
_SCOPE_LABELS = {"user": "Global (user)", "project": "Local (project)"}


def _supported_scopes(backend: HarnessBackend) -> list[str]:
    """The scopes this backend actually has a skills directory for, in canonical
    order. A harness that supports only one (e.g. hermes: user only) yields just
    that one, so it is never offered an impossible choice (REQ-08)."""
    return [
        scope
        for scope in SCOPES
        if getattr(backend, f"{scope}_skills_dir") is not None
    ]


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
        supported = _supported_scopes(backend)
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
