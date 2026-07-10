"""AGENTSQUIRE_HOME / AGENTSQUIRE_PROJECT root overrides (BUG-01).

When check_stale and the mounted skills group are wired the production way -
with no home=/project= arguments, so each invocation resolves the real roots -
a consumer's CLI-level test could previously only redirect them by
monkeypatching Path.home and chdir. These env vars let such a test set two
variables instead. Explicit home=/project= still win; an empty value is
treated as unset (the NO_COLOR convention already used for CI /
AGENTSQUIRE_NO_UPDATE_CHECK).

Every test here uses read-only surfaces (the notice, `skills status`) and
points HOME at a throwaway dir, so nothing can touch the real home even if the
override is not honored.
"""

import sys

import pytest
from click.testing import CliRunner

from agentsquire import CLAUDE_CODE, DirectorySource, check_stale, install
from agentsquire.cli import skills_command_group
from agentsquire.roots import resolve_home, resolve_project, resolve_roots

SKILL_MD = "---\nname: {name}\ndescription: A fixture skill.\n---\n\nbody\n"


def write_skill(root, name):
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL_MD.format(name=name))
    (skill / "reference.md").write_text(f"reference for {name}\n")


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME at an empty throwaway dir so Path.home() never hits the real
    home during a test - the override, if honored, is the only way to reach the
    fixtures."""
    throwaway = tmp_path / "throwaway-home"
    throwaway.mkdir()
    monkeypatch.setenv("HOME", str(throwaway))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_HOME", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_PROJECT", raising=False)


class TestResolver:
    def test_explicit_argument_beats_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTSQUIRE_HOME", str(tmp_path / "env"))
        explicit = tmp_path / "explicit"
        assert resolve_home(explicit) == explicit

    def test_env_used_when_argument_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTSQUIRE_HOME", str(tmp_path / "env-home"))
        monkeypatch.setenv("AGENTSQUIRE_PROJECT", str(tmp_path / "env-proj"))
        home, project = resolve_roots(None, None)
        assert home == tmp_path / "env-home"
        assert project == tmp_path / "env-proj"

    def test_empty_env_is_treated_as_unset(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTSQUIRE_HOME", "")
        monkeypatch.setenv("AGENTSQUIRE_PROJECT", "")
        monkeypatch.setenv("HOME", str(tmp_path / "real"))
        monkeypatch.chdir(tmp_path)
        assert resolve_home(None) == tmp_path / "real"
        assert resolve_project(None) == tmp_path


def make_installed(root, name="awiki-search"):
    """bundle + home (with .claude marker) + project; `name` installed up to date."""
    home = root / "home"
    project = root / "project"
    bundle = root / "bundle"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    bundle.mkdir()
    write_skill(bundle, name)
    source = DirectorySource(bundle)
    install(
        source, CLAUDE_CODE, scope="user", home=home, project=project,
        source_package="fixture-consumer", source_version="1.0.0",
    )
    return source, home, project, bundle


class TestCheckStaleEnvOverride:
    def test_notice_reaches_env_home_when_wired_without_fixture_args(
        self, tmp_path, monkeypatch, capsys, isolated_home
    ):
        source, home, project, bundle = make_installed(tmp_path)
        (bundle / "awiki-search" / "reference.md").write_text("v2\n")  # now stale
        monkeypatch.setenv("AGENTSQUIRE_HOME", str(home))
        monkeypatch.setenv("AGENTSQUIRE_PROJECT", str(project))

        # production wiring: no home=/project= -- the call a consumer really ships
        check_stale(
            source, CLAUDE_CODE, scope="user",
            prog_name="awiki", update_command="awiki skills update",
        )

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "awiki: a skills update is available for 1 skill (awiki-search);"
            " run `awiki skills update`\n"
        )


@pytest.fixture
def consumer_package(tmp_path, monkeypatch):
    """An importable package carrying one bundled skill as package data."""
    pkg = tmp_path / "pkgroot" / "fixture_consumer_pkg"
    skills = pkg / "skills" / "alpha"
    skills.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skills / "SKILL.md").write_text(SKILL_MD.format(name="alpha"))
    (skills / "reference.md").write_text("reference for alpha\n")
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, "fixture_consumer_pkg", raising=False)
    return "fixture_consumer_pkg", pkg


class TestGroupEnvOverride:
    def test_status_reads_env_home_when_group_wired_without_fixture_args(
        self, consumer_package, tmp_path, monkeypatch, isolated_home
    ):
        from agentsquire.sources import BundledPackageDataSource

        package, _ = consumer_package
        home = tmp_path / "home"
        project = tmp_path / "project"
        (home / ".claude").mkdir(parents=True)
        project.mkdir()
        # setup (not the code under test): install into the fixture home explicitly
        source = BundledPackageDataSource(package, "skills")
        install(
            source, CLAUDE_CODE, scope="user", home=home, project=project,
            source_package=package, source_version="1.2.3",
        )

        monkeypatch.setenv("AGENTSQUIRE_HOME", str(home))
        monkeypatch.setenv("AGENTSQUIRE_PROJECT", str(project))
        # group wired the production way: no home=/project=
        group = skills_command_group(package, default_scope="user")

        result = CliRunner().invoke(group, ["status", "--harness", "claude-code"])

        assert result.exit_code == 0, result.output
        assert "up-to-date alpha" in result.output
