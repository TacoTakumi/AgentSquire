"""Uninstall verb: remove only our-stamped installs (REQ-13).

Only skill directories whose provenance stamp names this library and the
consumer source package are removed. Same-named directories that are
unstamped or stamped by someone else survive the run, with the result
saying why each was left in place.
"""

from pathlib import Path

import pytest

from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.verbs import install, uninstall

PROVENANCE = {"source_package": "fixture-consumer", "source_version": "1.2.3"}


def write_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\nbody\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")
    return skill


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    source_root = tmp_path / "bundle"
    for directory in (home, project, source_root):
        directory.mkdir()
    return home, project, source_root


def run(verb, env, **overrides):
    home, project, source_root = env
    kwargs = dict(PROVENANCE)
    if verb is uninstall:
        del kwargs["source_version"]
    kwargs.update(overrides)
    return verb(
        DirectorySource(source_root),
        CLAUDE_CODE,
        scope="user",
        home=home,
        project=project,
        **kwargs,
    )


def test_our_stamped_install_is_removed(env):
    home, project, source_root = env
    write_skill(source_root, "alpha")
    run(install, env)
    installed = home / ".claude" / "skills" / "alpha"
    assert installed.is_dir()

    result = run(uninstall, env)

    assert [s.name for s in result.removed] == ["alpha"]
    assert not installed.exists()


def test_unstamped_same_named_directory_survives_with_a_reason(env):
    home, project, source_root = env
    write_skill(source_root, "alpha")
    theirs = home / ".claude" / "skills" / "alpha"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: the user's own skill\n---\nbody\n"
    )

    result = run(uninstall, env)

    assert result.removed == []
    assert [s.name for s in result.skipped] == ["alpha"]
    assert "stamp" in result.skipped[0].reason
    assert (theirs / "SKILL.md").is_file()


def test_foreign_stamped_directory_survives_with_a_reason(env):
    home, project, source_root = env
    write_skill(source_root, "alpha")
    run(install, env)

    result = run(uninstall, env, source_package="some-other-consumer")

    assert result.removed == []
    assert [s.name for s in result.skipped] == ["alpha"]
    assert "fixture-consumer" in result.skipped[0].reason
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()


def test_not_installed_skill_is_reported_not_removed(env):
    home, project, source_root = env
    write_skill(source_root, "alpha")

    result = run(uninstall, env)

    assert result.removed == []
    assert [s.name for s in result.skipped] == ["alpha"]
    assert result.skipped[0].reason == "not-installed"


def test_mixed_run_removes_only_ours(env):
    home, project, source_root = env
    write_skill(source_root, "ours")
    write_skill(source_root, "theirs")
    run(install, env)
    # overwrite "theirs" with an unstamped directory of the same name
    theirs = home / ".claude" / "skills" / "theirs"
    (theirs / "SKILL.md").write_text(
        "---\nname: theirs\ndescription: hand-made\n---\nbody\n"
    )
    stamp_line_gone = "agentsquire" not in (theirs / "SKILL.md").read_text()
    assert stamp_line_gone

    result = run(uninstall, env)

    assert [s.name for s in result.removed] == ["ours"]
    assert [s.name for s in result.skipped] == ["theirs"]
    assert not (home / ".claude" / "skills" / "ours").exists()
    assert theirs.is_dir()
