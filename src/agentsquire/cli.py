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
from dataclasses import dataclass
from pathlib import Path

import click

from agentsquire.harnesses import (
    SCOPES,
    HarnessBackend,
    HarnessNotDetectedError,
    UnknownHarnessError,
    UnsupportedScopeError,
    default_registry,
)
from agentsquire.roots import resolve_roots
from agentsquire.verbs import InstallResult
from agentsquire.verbs import install as install_verb
from agentsquire.verbs import status as status_verb
from agentsquire.verbs import uninstall as uninstall_verb
from agentsquire.verbs import update as update_verb
from agentsquire.sources import BundledPackageDataSource, SkillSource


def _consumer_version(package: str, source_package: str) -> str:
    try:
        return importlib.metadata.version(source_package)
    except importlib.metadata.PackageNotFoundError:
        return getattr(importlib.import_module(package), "__version__", "unknown")


@dataclass(frozen=True)
class HarnessTarget:
    """One (harness, scope) pair a verb operates on.

    ``explicit`` is True when the user named this harness — then a scope the
    backend lacks is a hard error; when False (a detected harness) it is a
    named skip, never an aborted run. This is the unit of a *plan* shared by
    every verb: install, status, update, and uninstall differ only in the verb
    they run per target, and the interactive front-end differs from the flag
    path only in how it builds the list of targets (REQ-14, REQ-15).
    """

    backend: HarnessBackend
    scope: str
    explicit: bool = False


@dataclass(frozen=True)
class InstallOutcome:
    """One target's structured result; ``result`` is None when the target was
    skipped because the backend lacks the requested scope (non-strict)."""

    target: HarnessTarget
    result: InstallResult | None


@dataclass(frozen=True)
class PlanExecution:
    """The structured outcome of running a whole install plan."""

    outcomes: list[InstallOutcome]

    @property
    def ok(self) -> bool:
        return all(o.result.ok for o in self.outcomes if o.result is not None)


def execute_install_plan(
    source: SkillSource,
    plan: list[HarnessTarget],
    *,
    home: Path,
    project: Path,
    source_package: str,
    source_version: str,
) -> PlanExecution:
    """Run an install plan and return its structured per-target results.

    One ``install`` verb call per (harness, scope) target, emitting the same
    per-skill output for every target. This is the single executor both the
    non-interactive flag path and the interactive front-end hand a plan to
    (REQ-15); it imports nothing from questionary/prompt_toolkit. A scope the
    backend lacks is a clean ClickException for an explicit target and a named
    skip otherwise — never an aborted multi-harness run.
    """
    outcomes: list[InstallOutcome] = []
    for target in plan:
        backend, scope = target.backend, target.scope
        try:
            result = install_verb(
                source, backend, scope=scope, home=home, project=project,
                source_package=source_package, source_version=source_version,
            )
        except UnsupportedScopeError as error:
            if target.explicit:
                raise click.ClickException(str(error)) from error
            click.echo(f"skipped {backend.name}: {error}", err=True)
            outcomes.append(InstallOutcome(target=target, result=None))
            continue
        for skill in result.installed:
            click.echo(f"installed {skill.name} -> {skill.path}")
        for skill in result.up_to_date:
            click.echo(f"up-to-date {skill.name} ({backend.name}/{scope})")
        for skill in result.skipped:
            click.echo(f"skipped {skill.name}: {skill.reason}", err=True)
        for violation in result.rejected:
            click.echo(f"invalid skill {violation.message}", err=True)
        outcomes.append(InstallOutcome(target=target, result=result))
    return PlanExecution(outcomes=outcomes)


def skills_command_group(
    package: str,
    resource_path: str = "skills",
    default_scope: str = "user",
    *,
    name: str = "skills",
    source_package: str | None = None,
    source_version: str | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> click.Group:
    """Build the mountable ``skills`` subcommand group for one consumer.

    ``package`` is the consumer's importable package carrying skills as
    package data under ``resource_path``; ``default_scope`` is the scope a
    plain invocation uses (--scope overrides it, REQ-14). ``source_package``
    and ``source_version`` default to the package name and its installed
    distribution (or ``__version__``) and end up in the provenance stamp.
    ``home`` and ``project`` point the group at explicit directories - tests
    pass fixture paths; production omits them and each invocation resolves
    the real ``Path.home()``/``Path.cwd()``.
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
    harness_multi_option = click.option(
        "--harness",
        "harnesses",
        multiple=True,
        metavar="NAME[:SCOPE]",
        help="Operate on this harness; repeatable, with an optional :scope "
        "suffix (default: all detected at --scope).",
    )

    def build_plan(harness_specs: tuple[str, ...], scope: str):
        """Resolve the repeatable --harness specs into a (plan, home, project).

        Shared by every verb (REQ-14). No specs keeps today's meaning — every
        detected harness at the top-level ``scope`` (REQ-11). Each
        ``NAME[:scope]`` spec selects one harness at its suffix scope, or the
        top-level ``scope`` when the suffix is omitted (REQ-10); a named
        harness that is unknown, undetected, or given an invalid/unsatisfiable
        scope is a clean, named error validated up front (REQ-12, REQ-13).
        """
        target_home, target_project = resolve_roots(home, project)
        registry = default_registry()
        if not harness_specs:
            backends = registry.detect(home=target_home, project=target_project)
            if not backends:
                raise click.ClickException("no supported harnesses detected")
            plan = [
                HarnessTarget(backend=backend, scope=scope, explicit=False)
                for backend in backends
            ]
            return plan, target_home, target_project
        plan = []
        for spec in harness_specs:
            name, _, suffix = spec.partition(":")
            target_scope = suffix or scope
            try:
                backend = registry.resolve(
                    name, home=target_home, project=target_project
                )
            except (UnknownHarnessError, HarnessNotDetectedError) as error:
                raise click.ClickException(str(error)) from error
            if target_scope not in SCOPES:
                raise click.ClickException(
                    f"harness {name!r}: unknown scope {target_scope!r}; "
                    f"expected one of {', '.join(SCOPES)}"
                )
            # Validate the whole plan before any write: an explicitly named
            # NAME:scope the backend cannot satisfy is a hard error here, so a
            # multi-target plan never partially installs (REQ-12, REQ-24).
            try:
                backend.skills_dir(
                    target_scope, home=target_home, project=target_project
                )
            except UnsupportedScopeError as error:
                raise click.ClickException(str(error)) from error
            plan.append(
                HarnessTarget(backend=backend, scope=target_scope, explicit=True)
            )
        return plan, target_home, target_project

    def run_target(target: HarnessTarget, invoke_verb):
        """One verb call on one plan target. A scope the backend lacks is a
        clean error for an explicitly named target and a named skip otherwise —
        never an aborted multi-harness run. (Explicit targets are validated in
        build_plan, so this branch is reached only for detected ones.)"""
        try:
            return invoke_verb()
        except UnsupportedScopeError as error:
            if target.explicit:
                raise click.ClickException(str(error)) from error
            click.echo(f"skipped {target.backend.name}: {error}", err=True)
            return None

    group = click.Group(name=name, help="Manage this package's bundled agent skills.")

    @group.command("install")
    @scope_option
    @harness_multi_option
    @click.pass_context
    def install(ctx, scope, harnesses):
        """Install bundled skills into detected harnesses."""
        plan, plan_home, plan_project = build_plan(harnesses, scope)
        execution = execute_install_plan(
            source, plan, home=plan_home, project=plan_project,
            source_package=src_pkg, source_version=src_version,
        )
        if not execution.ok:
            ctx.exit(1)

    @group.command("status")
    @scope_option
    @harness_multi_option
    def status(scope, harnesses):
        """Show each bundled skill's state per harness."""
        plan, home, project = build_plan(harnesses, scope)
        for target in plan:
            backend = target.backend
            statuses = run_target(target, lambda: status_verb(
                source, backend, scope=target.scope, home=home, project=project
            ))
            for skill in statuses or ():
                click.echo(
                    f"{skill.state.value} {skill.name} ({backend.name}/{target.scope})"
                )

    @group.command("update")
    @scope_option
    @harness_multi_option
    @click.option("--force", is_flag=True, help="Overwrite locally-modified installs.")
    @click.pass_context
    def update(ctx, scope, harnesses, force):
        """Update stale installed skills to the bundled version."""
        plan, home, project = build_plan(harnesses, scope)
        failed = False
        for target in plan:
            backend = target.backend
            result = run_target(target, lambda: update_verb(
                source, backend, scope=target.scope, home=home, project=project,
                source_package=src_pkg, source_version=src_version, force=force,
            ))
            if result is None:
                continue
            for skill in result.updated:
                click.echo(f"updated {skill.name} -> {skill.path}")
            for skill in result.up_to_date:
                click.echo(f"up-to-date {skill.name} ({backend.name}/{target.scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)
            for violation in result.rejected:
                click.echo(f"invalid skill {violation.message}", err=True)
            failed = failed or not result.ok
        if failed:
            ctx.exit(1)

    @group.command("uninstall")
    @scope_option
    @harness_multi_option
    def uninstall(scope, harnesses):
        """Remove installed skills this package's stamp owns."""
        plan, home, project = build_plan(harnesses, scope)
        for target in plan:
            backend = target.backend
            result = run_target(target, lambda: uninstall_verb(
                source, backend, scope=target.scope, home=home, project=project,
                source_package=src_pkg,
            ))
            if result is None:
                continue
            for skill in result.removed:
                click.echo(f"removed {skill.name} ({backend.name}/{target.scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)

    return group
