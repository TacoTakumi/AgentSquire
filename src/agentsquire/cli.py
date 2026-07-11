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
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from click.core import ParameterSource

from agentsquire.harnesses import (
    SCOPES,
    HarnessBackend,
    HarnessNotDetectedError,
    UnknownHarnessError,
    UnsupportedScopeError,
    default_registry,
)
from agentsquire.roots import resolve_roots
from agentsquire.stamping import read_stamp
from agentsquire.verbs import InstallResult
from agentsquire.verbs import install as install_verb
from agentsquire.verbs import status as status_verb
from agentsquire.verbs import uninstall as uninstall_verb
from agentsquire.verbs import update as update_verb
from agentsquire.sources import SkillSource, default_source


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


@dataclass(frozen=True)
class RemovableSkill:
    """One installed-and-ours skill directory: our provenance stamp names both
    ``agentsquire`` as installer and the consumer as source package. The unit of
    the interactive uninstall picker (REQ-22)."""

    name: str
    backend: HarnessBackend
    scope: str
    path: Path


def _is_ours(manifest_text: str, source_package: str) -> bool:
    """Whether a SKILL.md's provenance stamp marks it installed by us for this
    consumer — the same ownership test the uninstall verb applies (REQ-13)."""
    stamp = read_stamp(manifest_text)
    return (
        stamp is not None
        and stamp.get("installer") == "agentsquire"
        and stamp.get("source_package") == source_package
    )


def installed_and_ours(
    backends: list[HarnessBackend],
    *,
    source_package: str,
    home: Path,
    project: Path,
) -> list[RemovableSkill]:
    """Every installed-and-ours skill across the detected harnesses and each of
    their scopes, read from on-disk provenance stamps (REQ-22).

    Enumerates the actual skill directories on disk — not the source's skill
    list — so what is offered is exactly what is installed and stamped as ours;
    unstamped and foreign-stamped directories (and symlinks) are omitted. A
    physical directory is listed once even when two scopes resolve to it (e.g.
    claude-code's user and project skills dirs coincide when run from home).
    """
    found: list[RemovableSkill] = []
    seen: set[Path] = set()
    for backend in backends:
        for scope in backend.supported_scopes():
            root = backend.skills_dir(scope, home=home, project=project)
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.is_symlink() or not child.is_dir():
                    continue
                resolved = child.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                manifest = child / "SKILL.md"
                if manifest.is_file() and _is_ours(manifest.read_text(), source_package):
                    found.append(
                        RemovableSkill(
                            name=child.name, backend=backend, scope=scope, path=child
                        )
                    )
    return found


def execute_uninstall_plan(
    entries: list[RemovableSkill], *, source_package: str
) -> list[RemovableSkill]:
    """Remove exactly the selected installed-and-ours entries, re-checking each
    stamp immediately before deletion so a directory that changed hands since it
    was enumerated is left in place. Returns the entries actually removed."""
    removed: list[RemovableSkill] = []
    for entry in entries:
        manifest = entry.path / "SKILL.md"
        if entry.path.is_symlink() or not (
            manifest.is_file() and _is_ours(manifest.read_text(), source_package)
        ):
            click.echo(
                f"skipped {entry.name}: no longer ours "
                f"({entry.backend.name}/{entry.scope})",
                err=True,
            )
            continue
        shutil.rmtree(entry.path)
        click.echo(f"removed {entry.name} ({entry.backend.name}/{entry.scope})")
        removed.append(entry)
    return removed


def _stdin_is_interactive() -> bool:
    """Whether stdin is an interactive TTY. A thin, monkeypatchable wrapper so
    the auto-gate can be exercised in tests without a real terminal (REQ-17)."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _should_prompt(ctx, harnesses, assume_yes=False, no_input=False) -> bool:
    """Whether a verb should launch its interactive TUI (REQ-03, REQ-04).

    Only on an interactive TTY with none of --harness/--scope/-y/--no-input
    explicitly passed and no CI marker set. Explicitness of --scope is read from
    click's parameter source, so ``--scope user`` (equal to the default) still
    disables the TUI; any explicit flag, a non-TTY stdin, or a set CI variable
    runs the non-interactive flag path and constructs no prompt. Shared by
    install and uninstall; ``assume_yes``/``no_input`` default off for verbs
    that do not (yet) expose those flags.
    """
    if no_input or assume_yes or harnesses:
        return False
    if ctx.get_parameter_source("scope") == ParameterSource.COMMANDLINE:
        return False
    if os.environ.get("CI"):
        return False
    return _stdin_is_interactive()


def skills_command_group(
    package: str,
    resource_path: str = "skills",
    default_scope: str = "user",
    *,
    name: str = "skills",
    source: SkillSource | None = None,
    source_package: str | None = None,
    source_version: str | None = None,
    home: Path | None = None,
    project: Path | None = None,
) -> click.Group:
    """Build the mountable ``skills`` subcommand group for one consumer.

    ``package`` is the consumer's importable package carrying skills as
    package data under ``resource_path``; ``default_scope`` is the scope a
    plain invocation uses (--scope overrides it, REQ-14). The zero-arg default
    source is the two-root union of the package-data skills and the repo-level
    skills (REQ-18); pass a keyword-only ``source`` to use a specific
    ``SkillSource`` verbatim instead (REQ-07). ``source_package`` and
    ``source_version`` default to the package name and its installed
    distribution (or ``__version__``) and end up in the provenance stamp.
    ``home`` and ``project`` point the group at explicit directories - tests
    pass fixture paths; production omits them and each invocation resolves
    the real ``Path.home()``/``Path.cwd()``.
    """
    if source is None:
        source = default_source(package, resource_path)
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
    @click.option(
        "--no-input", is_flag=True, help="Never prompt; run non-interactively."
    )
    @click.option(
        "-y", "--yes", "assume_yes", is_flag=True,
        help="Assume yes to any confirmation.",
    )
    @click.pass_context
    def install(ctx, scope, harnesses, no_input, assume_yes):
        """Install bundled skills into detected harnesses.

        On an interactive terminal with no selection or control flag, prompts
        for which harnesses and scopes to install into; otherwise installs into
        the flag-selected targets (default: all detected at --scope).
        """
        if _should_prompt(ctx, harnesses, assume_yes, no_input):
            # Lazy import keeps questionary/prompt_toolkit out of a plain
            # ``import agentsquire.cli`` — they load only when actually
            # prompting (REQ-16).
            from agentsquire.interactive import gather_install_plan

            target_home, target_project = resolve_roots(home, project)
            backends = default_registry().detect(
                home=target_home, project=target_project
            )
            if not backends:
                raise click.ClickException("no supported harnesses detected")
            plan = gather_install_plan(backends, default_scope=scope)
            if plan is None:
                # Cancelled (Esc/Ctrl-C at any prompt): confirm is the single
                # last gate, so nothing was written (REQ-19, REQ-24).
                click.echo("Aborted; nothing was changed.", err=True)
                ctx.exit(1)
            if not plan:
                # Nothing selected, or the confirm was declined — a clean no-op.
                click.echo("Nothing to install.")
                return
            execution = execute_install_plan(
                source, plan, home=target_home, project=target_project,
                source_package=src_pkg, source_version=src_version,
            )
            if not execution.ok:
                ctx.exit(1)
            return
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
    @click.option(
        "--no-input", is_flag=True, help="Never prompt; run non-interactively."
    )
    @click.option(
        "-y", "--yes", "assume_yes", is_flag=True,
        help="Assume yes to the destructive confirm.",
    )
    @click.pass_context
    def uninstall(ctx, scope, harnesses, no_input, assume_yes):
        """Remove installed skills this package's stamp owns.

        On an interactive terminal with no selection flag, lists the
        installed-and-ours skills across all detected harnesses and scopes and
        lets you pick which to remove behind a destructive confirm (-y
        pre-answers it); otherwise removes them over the flag-selected targets
        (default: all detected at --scope).
        """
        # -y does not disable the picker here (unlike install): it pre-answers
        # the destructive confirm, so the assume_yes gate flag stays False.
        if _should_prompt(ctx, harnesses, no_input=no_input):
            from agentsquire.interactive import gather_uninstall_plan

            target_home, target_project = resolve_roots(home, project)
            backends = default_registry().detect(
                home=target_home, project=target_project
            )
            entries = installed_and_ours(
                backends, source_package=src_pkg,
                home=target_home, project=target_project,
            )
            if not entries:
                click.echo("Nothing installed by this package to uninstall.")
                return
            selection = gather_uninstall_plan(entries, assume_yes=assume_yes)
            if selection is None:
                click.echo("Aborted; nothing was changed.", err=True)
                ctx.exit(1)
            if not selection:
                click.echo("Nothing to uninstall.")
                return
            execute_uninstall_plan(selection, source_package=src_pkg)
            return
        plan, home_, project_ = build_plan(harnesses, scope)
        for target in plan:
            backend = target.backend
            result = run_target(target, lambda: uninstall_verb(
                source, backend, scope=target.scope, home=home_, project=project_,
                source_package=src_pkg,
            ))
            if result is None:
                continue
            for skill in result.removed:
                click.echo(f"removed {skill.name} ({backend.name}/{target.scope})")
            for skill in result.skipped:
                click.echo(f"skipped {skill.name}: {skill.reason}", err=True)

    return group
