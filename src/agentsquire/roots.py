"""Resolution of the home and project roots, with env-var overrides.

Explicit ``home=`` / ``project=`` arguments always win. When they are omitted
(the production wiring, where each invocation must resolve the real roots),
``AGENTSQUIRE_HOME`` / ``AGENTSQUIRE_PROJECT`` redirect the roots if set to a
non-empty value; otherwise the real ``Path.home()`` / ``Path.cwd()`` are used.

The env overrides exist so a consumer's CLI-level test can point the wired
staleness hook and the mounted ``skills`` subcommands at fixture directories by
setting two variables, instead of monkeypatching ``Path.home`` and chdir. An
empty-string value is treated as unset - the NO_COLOR convention already used
for ``CI`` and ``AGENTSQUIRE_NO_UPDATE_CHECK``.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME_ENV = "AGENTSQUIRE_HOME"
PROJECT_ENV = "AGENTSQUIRE_PROJECT"


def resolve_home(home: Path | None) -> Path:
    """The home root: explicit ``home`` if given, else ``$AGENTSQUIRE_HOME``
    (non-empty), else the real ``Path.home()``."""
    if home is not None:
        return home
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override)
    return Path.home()


def resolve_project(project: Path | None) -> Path:
    """The project root: explicit ``project`` if given, else
    ``$AGENTSQUIRE_PROJECT`` (non-empty), else the real ``Path.cwd()``."""
    if project is not None:
        return project
    override = os.environ.get(PROJECT_ENV)
    if override:
        return Path(override)
    return Path.cwd()


def resolve_roots(
    home: Path | None, project: Path | None
) -> tuple[Path, Path]:
    """``(home, project)`` roots with explicit args winning over env over real."""
    return resolve_home(home), resolve_project(project)
