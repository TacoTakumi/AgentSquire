"""The ``squire`` root CLI - agentsquire's own runnable executable.

``squire`` (and its long alias ``agentsquire``) is itself an agentsquire
consumer: it carries one bundled skill (developing-with-agentsquire) and, over
the coming tasks, mounts the skills subcommand group, a ``guide`` command, and
the proactive staleness notice. This module is that root command group; the two
console scripts in ``[project.scripts]`` both point here.
"""

from __future__ import annotations

from importlib.metadata import version

import click

from agentsquire.cli import skills_command_group

# The installed agentsquire version, and the single source of truth for
# ``--version`` (equals agentsquire.__version__, kept in sync by release tooling).
_VERSION = version("agentsquire")


@click.group()
@click.version_option(version=_VERSION, prog_name="squire", message="%(version)s")
def main() -> None:
    """squire - install agentsquire's own agent skills into your harness."""


# Dogfood the ready-made group agentsquire publishes: mount it the production
# way (no home=/project=), so each invocation resolves the real roots. Tests
# redirect those roots with AGENTSQUIRE_HOME / AGENTSQUIRE_PROJECT.
main.add_command(skills_command_group("agentsquire", default_scope="user"))
