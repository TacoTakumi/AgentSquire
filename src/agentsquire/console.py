"""The ``squire`` root CLI - agentsquire's own runnable executable.

``squire`` (and its long alias ``agentsquire``) is itself an agentsquire
consumer: it carries one bundled skill (developing-with-agentsquire), mounts the
skills subcommand group and a ``guide`` command, and emits the proactive
staleness notice. This module is that root command group; the two console
scripts in ``[project.scripts]`` both point here.
"""

from __future__ import annotations

from importlib.metadata import version
from importlib.resources import files as resource_files
from pathlib import Path

import click

import agentsquire
from agentsquire import check_stale
from agentsquire.cli import skills_command_group
from agentsquire.sources import default_source

# The installed agentsquire version, and the single source of truth for
# ``--version`` (equals agentsquire.__version__, kept in sync by release tooling).
_VERSION = version("agentsquire")

# The `guide` topics, one per canonical doc. Content is force-included into the
# wheel under agentsquire/_docs/<topic>.md (see pyproject); nothing is committed
# under the package, so a source checkout falls back to the repo docs/ + README.
_GUIDE_TOPICS = ("api", "harnesses", "integration")
_GUIDE_SOURCE_FALLBACK = {
    "api": ("docs", "api.md"),
    "harnesses": ("docs", "harnesses.md"),
    "integration": ("README.md",),
}


def _read_guide_doc(topic: str) -> str | None:
    """Content for a guide topic: the packaged agentsquire/_docs/<topic>.md when
    installed from a wheel, else the repo docs/ + README in a source checkout."""
    packaged = resource_files("agentsquire") / "_docs" / f"{topic}.md"
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    # Source checkout: <repo>/src/agentsquire/__init__.py -> repo root is parents[2].
    repo_root = Path(agentsquire.__file__).resolve().parents[2]
    fallback = repo_root.joinpath(*_GUIDE_SOURCE_FALLBACK[topic])
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return None


@click.group()
@click.version_option(version=_VERSION, prog_name="squire", message="%(version)s")
def main() -> None:
    """squire - install agentsquire's own agent skills into your harness."""
    # Proactive skill-staleness notice, wired the production way (no home=/
    # project=, so the real roots resolve). Uses the same two-root union the
    # skills group resolves through, so a Root B skill would be checked too.
    # Safe by design: notice-only on stderr, never prompts, never mutates,
    # never changes the exit code.
    check_stale(
        default_source("agentsquire"),
        prog_name="squire",
        update_command="squire skills update",
    )


@main.command()
@click.argument("topic", required=False)
def guide(topic: str | None) -> None:
    """Show agentsquire's reference docs. Run with no TOPIC to list them."""
    if topic is None:
        click.echo("Available guide topics:")
        for name in _GUIDE_TOPICS:
            click.echo(f"  {name}")
        return
    if topic not in _GUIDE_TOPICS:
        raise click.BadParameter(
            f"unknown topic {topic!r}. Available topics: "
            f"{', '.join(_GUIDE_TOPICS)}.",
            param_hint="TOPIC",
        )
    content = _read_guide_doc(topic)
    if content is None:
        raise click.ClickException(f"the {topic!r} guide doc is not available.")
    # Raw markdown via click.echo (no pager) for deterministic, capturable output.
    click.echo(content)


# Dogfood the ready-made group agentsquire publishes: mount it the production
# way (no home=/project=), so each invocation resolves the real roots. Tests
# redirect those roots with AGENTSQUIRE_HOME / AGENTSQUIRE_PROJECT.
main.add_command(skills_command_group("agentsquire", default_scope="user"))
