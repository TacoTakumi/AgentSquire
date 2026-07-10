"""Notice-only staleness check for consumer CLI startup.

One call, placed at the top of the consumer's entry point. With
update-available skills it prints a single advisory line on stderr naming
the real CLI and the exact update command. It never prompts, never touches
any input stream, never writes to stdout, never mutates installed skills,
never raises, and never changes the consumer command's exit code. The
explicit skills update verb is the sole updater. Decisions are local hash
compares only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from agentsquire.harnesses import HarnessBackend, default_registry
from agentsquire.roots import resolve_roots
from agentsquire.sources import SkillSource
from agentsquire.verbs import SkillState, status


def check_stale(
    source: SkillSource,
    backend: HarnessBackend | None = None,
    *,
    scope: str = "user",
    home: Path | None = None,
    project: Path | None = None,
    prog_name: str,
    update_command: str,
) -> None:
    """Print a one-line stderr notice when installed skills have updates.

    With no backend given, every detected harness is checked. Returns None
    always and swallows its own errors: a startup hook must never break, or
    change the exit code of, the consumer command it runs inside.
    """
    try:
        # Notice gate: any non-empty value of CI or AGENTSQUIRE_NO_UPDATE_CHECK
        # disables (presence-disables, the NO_COLOR convention; empty string
        # counts as unset). The notice is deliberately NOT gated on an
        # interactive TTY: the primary reader is an agent harness that runs the
        # consumer with captured (non-TTY) stderr and must still see that an
        # update is available. CI stays the escape hatch for pipelines.
        if os.environ.get("CI") or os.environ.get("AGENTSQUIRE_NO_UPDATE_CHECK"):
            return
        home, project = resolve_roots(home, project)
        backends = (
            [backend]
            if backend is not None
            else default_registry().detect(home=home, project=project)
        )
        stale_names = sorted(
            {
                skill.name
                for candidate in backends
                for skill in status(
                    source, candidate, scope=scope, home=home, project=project
                )
                if skill.state is SkillState.UPDATE_AVAILABLE
            }
        )
        if not stale_names:
            return
        count = len(stale_names)
        noun = "skill" if count == 1 else "skills"
        names = ", ".join(stale_names)
        print(
            f"{prog_name}: a skills update is available for"
            f" {count} {noun} ({names}); run `{update_command}`",
            file=sys.stderr,
        )
    except Exception:
        return
