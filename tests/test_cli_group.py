"""Mountable CLI subcommand group (REQ-14, REQ-15).

One factory call parameterized by (package, resource path, default scope)
returns a click group with install/status/update/uninstall. A click consumer
and a typer consumer each mount it with a single call and run all four verbs
end-to-end against fixture harness dirs; --scope overrides the declared
default; the library source names no consumer.
"""

import re
import sys
from pathlib import Path

import click
import pytest
import typer
import typer.main
from click.testing import CliRunner

from agentsquire.cli import skills_command_group

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


def test_library_source_names_no_consumer():
    src = Path(__file__).parent.parent / "src" / "agentsquire"
    offenders = []
    for file in src.rglob("*.py"):
        if re.search(r"awiki|specflo|agent[-_]wiki", file.read_text(), re.IGNORECASE):
            offenders.append(file.name)
    assert offenders == []
