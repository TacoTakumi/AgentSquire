"""Notice-only staleness check for consumer CLI startup.

One call, placed at the top of the consumer's entry point. With
update-available skills it prints a single advisory line on stderr naming
the real CLI and the exact update command. It never prompts, never touches
any input stream, never writes to stdout, never mutates installed skills,
never raises, and never changes the consumer command's exit code. The
explicit skills update verb is the sole updater. Decisions are local hash
compares only.

notify_update is the same kind of hook for releases of the consumer itself.
It reads the release cache, which an explicit release check wrote before,
and compares the cached newest version with the installed one. It makes no
network request and never writes the cache. With a newer release it prints
one line on stderr, under the same rules as above.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from agentsquire import _install, _release_cache, release
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


def notify_update(
    distribution: str,
    version: str | None = None,
    *,
    prog_name: str,
) -> None:
    """Print a one-line stderr notice when the cache holds a newer release.

    The installed version is the one passed, else the one in the install
    metadata. The comparison runs at each call against the cached newest
    version, of any age. Nothing is printed when there is no usable cache,
    when the installed version is not older, or when a version does not
    parse. The line ends with the upgrade command when the install method is
    known. Returns None always and swallows its own errors.
    """
    try:
        # The same notice gate as check_stale: a non-empty CI or
        # AGENTSQUIRE_NO_UPDATE_CHECK disables, an empty value counts as
        # unset, and there is no TTY gate.
        if os.environ.get("CI") or os.environ.get("AGENTSQUIRE_NO_UPDATE_CHECK"):
            return
        newest = _release_cache.read_cache(distribution)
        if newest is None:
            return
        installed = (
            version if version is not None else _install.installed_version(distribution)
        )
        status = release.compare_versions(installed, newest)
        if status is not release.ReleaseStatus.UPDATE_AVAILABLE:
            return
        line = f"{prog_name}: a new release is available: {installed} -> {newest}"
        command = _install.upgrade_command(distribution)
        if command:
            line += f"; run `{command}`"
        print(line, file=sys.stderr)
    except Exception:
        return
