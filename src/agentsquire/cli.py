"""Ready-made CLI subcommand group consumers mount into their own CLI.

One factory call — parameterized by (package, resource path, default scope) —
returns a click group with install/status/update/uninstall, so a consumer CLI
exposes e.g. ``<consumer> skills install`` with no glue code (REQ-15). The
group works identically mounted into a click app or a typer app via typer's
click compatibility. It carries no consumer-specific logic; everything the
consumer-specific comes in through the factory parameters.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path

import click

from agentsquire.harnesses import (
    SCOPES,
    HarnessNotDetectedError,
    UnknownHarnessError,
    UnsupportedScopeError,
    default_registry,
)
from agentsquire.verbs import install as install_verb
from agentsquire.verbs import status as status_verb
from agentsquire.verbs import uninstall as uninstall_verb
from agentsquire.verbs import update as update_verb
from agentsquire.sources import BundledPackageDataSource


def _consumer_version(package: str, source_package: str) -> str:
    try:
        return importlib.metadata.version(source_package)
    except importlib.metadata.PackageNotFoundError:
        return getattr(importlib.import_module(package), "__version__", "unknown")


def skills_command_group(
    package: str,
    resource_path: str = "skills",
    default_scope: str = "user",
    *,
    name: str = "skills",
    source_package: str | None = None,
    source_version: str | None = None,
) -> click.Group:
    """Build the mountable ``skills`` subcommand group for one consumer.

    ``package`` is the consumer's importable package carrying skills as
    package data under ``resource_path``; ``default_scope`` is the scope a
    plain invocation uses (--scope overrides it, REQ-14). ``source_package``
    and ``source_version`` default to the package name and its installed
    distribution (or ``__version__``) and end up in the provenance stamp.
    """
    source = BundledPackageDataSource(package, resource_path)
    src_pkg = source_package or package
    src_version = source_version or _consumer_version(package, src_pkg)

    scope_option = click.option(
        "--scope",
        type=click.Choice(SCOPES),
        default=default_scope,
        show_default=True,
        help="Which harness skills directory to operate on.",
    )
    harness_option = click.option(
        "--harness",
        default=None,
        metavar="NAME",
        help="Operate on one harness (default: all detected).",
    )

    def targets(harness: str | None):
        """(backends, home, project) for this invocation, or a clear error."""
        home, project = Path.home(), Path.cwd()
        registry = default_registry()
        if harness is not None:
            try:
                backends = [registry.resolve(harness, home=home, project=project)]
            except (UnknownHarnessError, HarnessNotDetectedError) as error:
                raise click.ClickException(str(error)) from error
        else:
            backends = registry.detect(home=home, project=project)
            if not backends:
                raise click.ClickException("no supported harnesses detected")
        return backends, home, project

    def run_on(backend, harness, invoke_verb):
        """One verb call on one backend. A scope the backend lacks is a clean
        error when that harness was asked for, a named skip otherwise — never
        an aborted multi-harness run."""
        try:
            return invoke_verb()
        except UnsupportedScopeError as error:
            if harness is not None:
                raise click.ClickException(str(error)) from error
            click.echo(f"skipped {backend.name}: {error}", err=True)
            return None

    group = click.Group(name=name, help="Manage this package's bundled agent skills.")

    @group.command("install")
    @scope_option
    @harness_option
    @click.pass_context
    def install(ctx, scope, harness):
        """Install bundled skills into detected harnesses."""
        backends, home, project = targets(harness)
        failed = False
        for backend in backends:
            result = run_on(backend, harness, lambda: install_verb(
                source, backend, scope=scope, home=home, project=project,
                source_package=src_pkg, source_version=src_version,
            ))
            if result is None:
                continue
            for skill in result.installed:
                click.echo(f"installed {skill.name} -> {skill.path}")
            for skill in result.up_to_date:
                click.echo(f"up-to-date {skill.name} ({backend.name}/{scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)
            for violation in result.rejected:
                click.echo(f"invalid skill {violation.message}", err=True)
            failed = failed or not result.ok
        if failed:
            ctx.exit(1)

    @group.command("status")
    @scope_option
    @harness_option
    def status(scope, harness):
        """Show each bundled skill's state per harness."""
        backends, home, project = targets(harness)
        for backend in backends:
            statuses = run_on(backend, harness, lambda: status_verb(
                source, backend, scope=scope, home=home, project=project
            ))
            for skill in statuses or ():
                click.echo(f"{skill.state.value} {skill.name} ({backend.name}/{scope})")

    @group.command("update")
    @scope_option
    @harness_option
    @click.option("--force", is_flag=True, help="Overwrite locally-modified installs.")
    @click.pass_context
    def update(ctx, scope, harness, force):
        """Update stale installed skills to the bundled version."""
        backends, home, project = targets(harness)
        failed = False
        for backend in backends:
            result = run_on(backend, harness, lambda: update_verb(
                source, backend, scope=scope, home=home, project=project,
                source_package=src_pkg, source_version=src_version, force=force,
            ))
            if result is None:
                continue
            for skill in result.updated:
                click.echo(f"updated {skill.name} -> {skill.path}")
            for skill in result.up_to_date:
                click.echo(f"up-to-date {skill.name} ({backend.name}/{scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)
            for violation in result.rejected:
                click.echo(f"invalid skill {violation.message}", err=True)
            failed = failed or not result.ok
        if failed:
            ctx.exit(1)

    @group.command("uninstall")
    @scope_option
    @harness_option
    def uninstall(scope, harness):
        """Remove installed skills this package's stamp owns."""
        backends, home, project = targets(harness)
        for backend in backends:
            result = run_on(backend, harness, lambda: uninstall_verb(
                source, backend, scope=scope, home=home, project=project,
                source_package=src_pkg,
            ))
            if result is None:
                continue
            for skill in result.removed:
                click.echo(f"removed {skill.name} ({backend.name}/{scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)

    return group
