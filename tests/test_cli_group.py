"""Mountable CLI subcommand group (REQ-14, REQ-15).

One factory call parameterized by (package, resource path, default scope)
returns a click group with install/status/update/uninstall. A click consumer
and a typer consumer each mount it with a single call and run all four verbs
end-to-end against fixture harness dirs; --scope overrides the declared
default; the library source names no consumer.
"""

import ast
import inspect
import re
import shutil
import sys
from pathlib import Path

import click
import pytest
import typer
import typer.main
from click.testing import CliRunner

from agentsquire.cli import (
    HarnessTarget,
    _consumer_version,
    execute_install_plan,
    skills_command_group,
)
from agentsquire.harnesses import default_registry
from agentsquire.sources import BundledPackageDataSource

SKILL_MD = "---\nname: alpha\ndescription: A fixture skill.\n---\n\nbody\n"


@pytest.fixture
def consumer_package(tmp_path, monkeypatch):
    """An importable package carrying one bundled skill as package data."""
    pkg = tmp_path / "pkgroot" / "fixture_consumer_pkg"
    skills = pkg / "skills" / "alpha"
    skills.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skills / "SKILL.md").write_text(SKILL_MD)
    (skills / "reference.md").write_text("reference for alpha\n")
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    # each test gets its own package tree; evict any cached import of it
    monkeypatch.delitem(sys.modules, "fixture_consumer_pkg", raising=False)
    return "fixture_consumer_pkg", pkg


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake home + project cwd with the Claude Code marker present in home."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)
    return home, project


@pytest.fixture
def click_consumer(consumer_package):
    package, _ = consumer_package

    @click.group()
    def cli():
        """Fixture click consumer."""

    cli.add_command(skills_command_group(package, default_scope="user"))
    return cli


def invoke(app, *args):
    result = CliRunner().invoke(app, args, catch_exceptions=False)
    return result


class TestClickConsumer:
    def test_all_four_verbs_end_to_end(self, click_consumer, consumer_package, env):
        home, project = env
        _, pkg = consumer_package
        installed = home / ".claude" / "skills" / "alpha"

        result = invoke(click_consumer, "skills", "install")
        assert result.exit_code == 0, result.output
        assert installed.is_dir()

        result = invoke(click_consumer, "skills", "status")
        assert result.exit_code == 0
        assert "up-to-date" in result.output and "alpha" in result.output

        (pkg / "skills" / "alpha" / "reference.md").write_text("v2\n")
        result = invoke(click_consumer, "skills", "status")
        assert "update-available" in result.output

        result = invoke(click_consumer, "skills", "update")
        assert result.exit_code == 0
        assert (installed / "reference.md").read_text() == "v2\n"

        result = invoke(click_consumer, "skills", "uninstall")
        assert result.exit_code == 0
        assert not installed.exists()

    def test_plain_install_honors_declared_default_scope(
        self, click_consumer, env
    ):
        home, project = env

        invoke(click_consumer, "skills", "install")

        assert (home / ".claude" / "skills" / "alpha").is_dir()
        assert not (project / ".claude" / "skills").exists()

    def test_scope_flag_overrides_the_default(self, click_consumer, env):
        home, project = env

        result = invoke(click_consumer, "skills", "install", "--scope", "project")

        assert result.exit_code == 0, result.output
        assert (project / ".claude" / "skills" / "alpha").is_dir()
        assert not (home / ".claude" / "skills").exists()


class TestTyperConsumer:
    def test_single_call_mount_and_full_lifecycle(self, consumer_package, env):
        package, _ = consumer_package
        home, project = env
        app = typer.Typer()

        @app.callback()
        def main():
            """Fixture typer consumer."""

        @app.command()
        def hello():
            """Fixture typer consumer command."""

        click_app = typer.main.get_command(app)
        click_app.add_command(skills_command_group(package, default_scope="user"))

        assert invoke(click_app, "skills", "install").exit_code == 0
        assert (home / ".claude" / "skills" / "alpha").is_dir()
        assert "up-to-date" in invoke(click_app, "skills", "status").output
        assert invoke(click_app, "skills", "update").exit_code == 0
        assert invoke(click_app, "skills", "uninstall").exit_code == 0
        assert not (home / ".claude" / "skills" / "alpha").exists()


class TestHarnessSelection:
    def test_unknown_harness_errors_and_lists_supported(self, click_consumer, env):
        result = invoke(click_consumer, "skills", "install", "--harness", "emacs")

        assert result.exit_code != 0
        assert "claude-code" in result.output

    def test_undetected_harness_errors_clearly(self, click_consumer, env):
        result = invoke(click_consumer, "skills", "install", "--harness", "hermes")

        assert result.exit_code != 0
        assert "not detected" in result.output

    def test_zero_detected_harnesses_is_a_clear_error(
        self, click_consumer, tmp_path, monkeypatch
    ):
        home = tmp_path / "bare_home"
        project = tmp_path / "bare_project"
        home.mkdir()
        project.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.chdir(project)

        result = invoke(click_consumer, "skills", "install")

        assert result.exit_code != 0
        assert "no supported harnesses detected" in result.output

    def test_scope_unsupported_on_one_detected_harness_is_skipped(
        self, click_consumer, env
    ):
        home, project = env
        (home / ".hermes").mkdir()  # detected alongside claude-code; no project scope

        result = invoke(click_consumer, "skills", "install", "--scope", "project")

        assert result.exit_code == 0, result.output
        assert (project / ".claude" / "skills" / "alpha").is_dir()
        assert "hermes" in result.output  # named as skipped, run not aborted

    def test_scope_unsupported_on_the_explicit_harness_errors_clearly(
        self, click_consumer, env
    ):
        home, project = env
        (home / ".hermes").mkdir()

        result = invoke(
            click_consumer, "skills", "install", "--harness", "hermes",
            "--scope", "project",
        )

        assert result.exit_code != 0
        assert "no project-scope skills directory" in result.output


class TestRepeatableHarnessInstall:
    """REQ-10/REQ-11: --harness is repeatable with an optional :scope suffix;
    subset selection with per-target scope, omit = all detected at --scope."""

    def test_repeatable_harness_with_per_target_scope(self, click_consumer, env):
        home, project = env
        (home / ".pi").mkdir()  # detect pi alongside claude-code

        result = invoke(
            click_consumer, "skills", "install",
            "--harness", "claude-code:project", "--harness", "pi",
        )

        assert result.exit_code == 0, result.output
        # claude-code installed at its :project suffix scope, not the default user
        assert (project / ".claude" / "skills" / "alpha").is_dir()
        assert not (home / ".claude" / "skills" / "alpha").exists()
        # pi installed at the top-level default (user) scope
        assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()
        assert not (project / ".pi" / "skills" / "alpha").exists()

    def test_single_harness_no_suffix_targets_only_that_harness(
        self, click_consumer, env
    ):
        home, project = env
        (home / ".pi").mkdir()

        result = invoke(click_consumer, "skills", "install", "--harness", "claude-code")

        assert result.exit_code == 0, result.output
        assert (home / ".claude" / "skills" / "alpha").is_dir()
        assert not (home / ".pi" / "agent" / "skills" / "alpha").exists()

    def test_omitting_harness_installs_all_detected_at_scope(
        self, click_consumer, env
    ):
        home, project = env
        (home / ".pi").mkdir()

        result = invoke(click_consumer, "skills", "install")

        assert result.exit_code == 0, result.output
        assert (home / ".claude" / "skills" / "alpha").is_dir()
        assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()


class TestInstallTargetErrors:
    """REQ-12/REQ-13: unresolvable --harness install targets produce named
    errors, exit non-zero, and write nothing."""

    def test_unknown_harness_name_errors(self, click_consumer, env):
        home, _ = env

        result = invoke(click_consumer, "skills", "install", "--harness", "bogus")

        assert result.exit_code != 0
        assert "unknown harness" in result.output and "bogus" in result.output
        assert not (home / ".claude" / "skills").exists()

    def test_supported_but_undetected_harness_errors(self, click_consumer, env):
        home, _ = env

        result = invoke(click_consumer, "skills", "install", "--harness", "pi")

        assert result.exit_code != 0
        assert "not detected" in result.output
        assert not (home / ".claude" / "skills").exists()

    def test_invalid_scope_suffix_names_the_scope(self, click_consumer, env):
        home, project = env

        result = invoke(
            click_consumer, "skills", "install", "--harness", "claude-code:banana"
        )

        assert result.exit_code != 0
        assert "banana" in result.output
        assert not (home / ".claude" / "skills").exists()
        assert not (project / ".claude" / "skills").exists()

    def test_unsatisfiable_named_scope_names_harness_and_scope(
        self, click_consumer, env
    ):
        home, _ = env
        (home / ".hermes").mkdir()  # detected, but has no project scope

        result = invoke(
            click_consumer, "skills", "install", "--harness", "hermes:project"
        )

        assert result.exit_code != 0
        assert "hermes" in result.output and "project" in result.output
        assert not (home / ".hermes" / "skills").exists()

    def test_no_partial_write_when_a_later_explicit_target_is_unsatisfiable(
        self, click_consumer, env
    ):
        home, _ = env
        (home / ".hermes").mkdir()

        result = invoke(
            click_consumer, "skills", "install",
            "--harness", "claude-code", "--harness", "hermes:project",
        )

        assert result.exit_code != 0
        # The earlier claude-code target must not have been written before the
        # unsatisfiable hermes:project target aborted the plan (REQ-24).
        assert not (home / ".claude" / "skills" / "alpha").exists()


class TestRepeatableHarnessAcrossVerbs:
    """REQ-14: repeatable --harness NAME[:scope] resolves the same way for
    status, update, and uninstall as it does for install."""

    def test_status_subset_and_per_target_scope(self, click_consumer, env):
        home, _ = env
        (home / ".pi").mkdir()

        result = invoke(
            click_consumer, "skills", "status",
            "--harness", "claude-code:project", "--harness", "pi",
        )

        assert result.exit_code == 0, result.output
        assert "(claude-code/project)" in result.output
        assert "(pi/user)" in result.output

    def test_status_unknown_harness_errors(self, click_consumer, env):
        result = invoke(click_consumer, "skills", "status", "--harness", "bogus")

        assert result.exit_code != 0
        assert "unknown harness" in result.output

    def test_update_targets_the_suffix_scope(
        self, click_consumer, consumer_package, env
    ):
        _, pkg = consumer_package
        _, project = env
        assert invoke(
            click_consumer, "skills", "install", "--harness", "claude-code:project"
        ).exit_code == 0
        installed = project / ".claude" / "skills" / "alpha"
        assert installed.is_dir()
        (pkg / "skills" / "alpha" / "reference.md").write_text("v2\n")

        result = invoke(
            click_consumer, "skills", "update", "--harness", "claude-code:project"
        )

        assert result.exit_code == 0, result.output
        assert (installed / "reference.md").read_text() == "v2\n"

    def test_update_unsatisfiable_named_scope_errors(self, click_consumer, env):
        home, _ = env
        (home / ".hermes").mkdir()

        result = invoke(
            click_consumer, "skills", "update", "--harness", "hermes:project"
        )

        assert result.exit_code != 0
        assert "hermes" in result.output and "project" in result.output

    def test_uninstall_subset_and_per_target_scope(self, click_consumer, env):
        home, project = env
        (home / ".pi").mkdir()
        assert invoke(
            click_consumer, "skills", "install",
            "--harness", "claude-code:project", "--harness", "pi",
        ).exit_code == 0
        claude_at_project = project / ".claude" / "skills" / "alpha"
        pi_at_user = home / ".pi" / "agent" / "skills" / "alpha"
        assert claude_at_project.is_dir() and pi_at_user.is_dir()

        result = invoke(
            click_consumer, "skills", "uninstall", "--harness", "claude-code:project"
        )

        assert result.exit_code == 0, result.output
        assert not claude_at_project.exists()  # only the named subset target removed
        assert pi_at_user.is_dir()             # the other harness is untouched


class TestFailures:
    def test_invalid_bundled_skill_exits_nonzero_and_valid_still_installs(
        self, click_consumer, consumer_package, env
    ):
        home, project = env
        _, pkg = consumer_package
        bad = pkg / "skills" / "broken"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: not-broken\ndescription: d\n---\nx\n")

        result = invoke(click_consumer, "skills", "install")

        assert result.exit_code != 0
        assert "broken" in result.output
        assert (home / ".claude" / "skills" / "alpha").is_dir()


class TestCommandGroupInjection:
    """REQ-08: keyword home/project params, resolved lazily in targets()."""

    def test_command_group_signature_has_home_and_project_defaulting_none(self):
        params = inspect.signature(skills_command_group).parameters
        assert params["home"].default is None
        assert params["project"].default is None

    def test_command_group_with_injected_dirs_needs_no_monkeypatch_or_chdir(
        self, consumer_package, tmp_path
    ):
        package, _ = consumer_package
        home = tmp_path / "fixture_home"
        project = tmp_path / "fixture_project"
        (home / ".claude").mkdir(parents=True)
        project.mkdir()

        group = skills_command_group(
            package, default_scope="user", home=home, project=project
        )

        result = invoke(group, "install")
        assert result.exit_code == 0
        assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").exists()

        result = invoke(group, "status")
        assert result.exit_code == 0
        assert "alpha" in result.output

    def test_command_group_omitting_dirs_resolves_lazily_at_invocation(
        self, consumer_package, tmp_path, monkeypatch
    ):
        package, _ = consumer_package
        group = skills_command_group(package, default_scope="user")
        # Path.home/cwd change only after the group is built: install must
        # still land in them, proving targets() resolves per invocation.
        home = tmp_path / "late_home"
        project = tmp_path / "late_project"
        (home / ".claude").mkdir(parents=True)
        project.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        monkeypatch.chdir(project)

        result = invoke(group, "install")

        assert result.exit_code == 0
        assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").exists()


class TestInstallPlanExecutor:
    """REQ-15/REQ-06: install resolves to an explicit (harness, scope) plan run
    by one prompt_toolkit-free executor that both paths share."""

    def test_executor_module_imports_no_tui_libraries(self):
        cli_path = Path(__file__).parent.parent / "src" / "agentsquire" / "cli.py"
        imported: set[str] = set()
        for node in ast.walk(ast.parse(cli_path.read_text())):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "questionary" not in imported
        assert "prompt_toolkit" not in imported

    def test_execute_install_plan_returns_structured_per_target_results(
        self, consumer_package, env
    ):
        package, _ = consumer_package
        home, project = env
        source = BundledPackageDataSource(package, "skills")
        backends = default_registry().detect(home=home, project=project)
        plan = [HarnessTarget(backend=backend, scope="user") for backend in backends]

        execution = execute_install_plan(
            source,
            plan,
            home=home,
            project=project,
            source_package=package,
            source_version=_consumer_version(package, package),
        )

        assert execution.ok
        assert [target.backend.name for target in plan] == ["claude-code"]
        installed = [
            skill.name
            for outcome in execution.outcomes
            for skill in outcome.result.installed
        ]
        assert installed == ["alpha"]
        assert (home / ".claude" / "skills" / "alpha").is_dir()

    def test_executor_reproduces_the_flag_install_output(self, consumer_package, env):
        package, _ = consumer_package
        home, project = env
        installed = home / ".claude" / "skills" / "alpha"
        source = BundledPackageDataSource(package, "skills")

        group = skills_command_group(
            package, default_scope="user", home=home, project=project
        )
        flag = invoke(group, "install")
        assert flag.exit_code == 0, flag.output
        flag_output = flag.output

        # Reset so the direct run's installed paths match byte-for-byte.
        shutil.rmtree(installed)

        @click.command()
        @click.pass_context
        def run_plan(ctx):
            backends = default_registry().detect(home=home, project=project)
            plan = [HarnessTarget(backend=b, scope="user") for b in backends]
            execution = execute_install_plan(
                source,
                plan,
                home=home,
                project=project,
                source_package=package,
                source_version=_consumer_version(package, package),
            )
            if not execution.ok:
                ctx.exit(1)

        direct = invoke(run_plan)
        assert direct.exit_code == 0, direct.output
        assert direct.output == flag_output
        assert installed.is_dir()


def test_library_source_names_no_consumer():
    src = Path(__file__).parent.parent / "src" / "agentsquire"
    offenders = []
    for file in src.rglob("*.py"):
        if re.search(r"awiki|specflo|agent[-_]wiki", file.read_text(), re.IGNORECASE):
            offenders.append(file.name)
    assert offenders == []
