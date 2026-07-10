"""Proactive staleness check for consumer CLI startup (REQ-17, D-07).

One call, placed at the top of the consumer's entry point. On an interactive
terminal with update-available skills it announces them on stderr and offers
to run the update. Without a TTY it never prompts or blocks, writes nothing
to stdout, emits at most one stderr notice line, and never changes the
consumer command's exit code. Decisions are local hash compares only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agentsquire.harnesses import HarnessBackend, default_registry
from agentsquire.sources import SkillSource
from agentsquire.verbs import SkillState, status, update


def check_stale(
    source: SkillSource,
    backend: HarnessBackend | None = None,
    *,
    scope: str = "user",
    home: Path | None = None,
    project: Path | None = None,
    source_package: str,
    source_version: str,
) -> None:
    """Announce update-available skills and, on an accepted TTY prompt, update.

    With no backend given, every detected harness is checked. Returns None
    always and swallows its own errors: a startup hook must never break, or
    change the exit code of, the consumer command it runs inside.
    """
    try:
        home = home or Path.home()
        project = project or Path.cwd()
        backends = (
            [backend]
            if backend is not None
            else default_registry().detect(home=home, project=project)
        )
        stale = [
            (candidate, skill)
            for candidate in backends
            for skill in status(source, candidate, scope=scope, home=home, project=project)
            if skill.state is SkillState.UPDATE_AVAILABLE
        ]
        if not stale:
            return
        stale_names = sorted({skill.name for _, skill in stale})
        count, names = len(stale_names), ", ".join(stale_names)

        interactive = sys.stdin.isatty() and sys.stderr.isatty()
        if not interactive:
            print(
                f"{source_package}: a new version is available for"
                f" {count} skill(s) ({names}); run the skills update command",
                file=sys.stderr,
            )
            return

        print(
            f"{source_package}: a new version is available for"
            f" {count} skill(s): {names}",
            file=sys.stderr,
        )
        sys.stderr.write("Update now? [y/N] ")
        sys.stderr.flush()
        try:
            answer = sys.stdin.readline().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            return
        for candidate in dict.fromkeys(candidate for candidate, _ in stale):
            result = update(
                source,
                candidate,
                scope=scope,
                home=home,
                project=project,
                source_package=source_package,
                source_version=source_version,
            )
            for skill in result.updated:
                print(f"updated {skill.name} ({candidate.name})", file=sys.stderr)
    except Exception:
        return
