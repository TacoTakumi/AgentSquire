"""T-03 / REQ-04, REQ-05, REQ-11, REQ-01: the squire CLI mounts the skills group
and installs its one bundled skill into a detected harness end-to-end.

The group is wired the production way (no home=/project=); these CLI-level tests
redirect the roots with AGENTSQUIRE_HOME / AGENTSQUIRE_PROJECT (0.2.0 overrides)
rather than monkeypatching Path.home / chdir."""

import agentsquire
from agentsquire.console import main
from agentsquire.stamping import read_stamp
from click.testing import CliRunner

SKILL = "developing-with-agentsquire"


def invoke(*args, **env):
    return CliRunner().invoke(main, list(args), env=env, catch_exceptions=False)


def fixture_roots(tmp_path):
    """A home carrying the Claude Code marker, and an empty project dir."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    return home, project


def test_skills_help_lists_exactly_the_four_verbs():
    # REQ-04: the mounted group exposes exactly install/status/update/uninstall.
    skills_group = main.commands["skills"]
    assert sorted(skills_group.commands) == ["install", "status", "uninstall", "update"]

    result = invoke("skills", "--help")
    assert result.exit_code == 0
    for verb in ("install", "status", "update", "uninstall"):
        assert verb in result.output


def test_install_help_shows_scope_default_user_and_harness():
    # REQ-04: install exposes --scope (shown default user) and --harness.
    result = invoke("skills", "install", "--help")
    assert result.exit_code == 0
    assert "--scope" in result.output
    assert "[default: user]" in result.output
    assert "--harness" in result.output


def test_install_writes_stamped_skill_then_reports_up_to_date(tmp_path):
    # REQ-05/REQ-11: install writes the one bundled skill into the user-scope
    # Claude Code dir with an agentsquire provenance stamp, idempotently.
    home, project = fixture_roots(tmp_path)
    env = {"AGENTSQUIRE_HOME": str(home), "AGENTSQUIRE_PROJECT": str(project)}

    first = invoke("skills", "install", **env)
    assert first.exit_code == 0, first.output

    installed = home / ".claude" / "skills" / SKILL / "SKILL.md"
    assert installed.is_file()
    stamp = read_stamp(installed.read_text())
    assert stamp is not None
    assert stamp["installer"] == "agentsquire"
    assert stamp["source_package"] == "agentsquire"
    assert stamp["installer_version"] == agentsquire.__version__

    second = invoke("skills", "install", **env)
    assert second.exit_code == 0, second.output
    assert "up-to-date" in second.output


def test_status_lists_exactly_the_one_bundled_skill(tmp_path):
    # REQ-11: status over the user scope names exactly developing-with-agentsquire.
    home, project = fixture_roots(tmp_path)
    env = {"AGENTSQUIRE_HOME": str(home), "AGENTSQUIRE_PROJECT": str(project)}

    result = invoke("skills", "status", "--scope", "user", **env)
    assert result.exit_code == 0, result.output

    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1
    assert SKILL in lines[0]
