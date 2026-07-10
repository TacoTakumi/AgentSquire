"""Status verb + install idempotency (REQ-10, REQ-11).

Each skill x harness x scope classifies as exactly one of not-installed /
up-to-date / update-available / locally-modified, from local hash compares
only (verified with socket creation disabled). Install consults the same
classification, so re-installing a current skill is a byte-identical no-op
reported as up-to-date.
"""

import socket
from pathlib import Path

import pytest

from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.verbs import SkillState, install, status

PROVENANCE = {"source_package": "fixture-consumer", "source_version": "1.2.3"}


def write_skill(root: Path, name: str, body: str = "body\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\n{body}"
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


def run(verb, env):
    home, project, source_root = env
    return verb(
        DirectorySource(source_root),
        CLAUDE_CODE,
        scope="user",
        home=home,
        project=project,
        **(PROVENANCE if verb is install else {}),
    )


def state_of(env, name):
    states = {s.name: s.state for s in run(status, env)}
    return states[name]


class TestClassification:
    def test_not_installed(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        assert state_of(env, "alpha") is SkillState.NOT_INSTALLED

    def test_up_to_date(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)

        assert state_of(env, "alpha") is SkillState.UP_TO_DATE

    def test_update_available_when_source_moves_on(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        (source_root / "alpha" / "reference.md").write_text("v2 reference\n")

        assert state_of(env, "alpha") is SkillState.UPDATE_AVAILABLE

    def test_locally_modified_when_installed_copy_is_edited(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        (home / ".claude" / "skills" / "alpha" / "reference.md").write_text("edited\n")

        assert state_of(env, "alpha") is SkillState.LOCALLY_MODIFIED

    def test_unstamped_directory_of_same_name_is_locally_modified(self, env):
        """A same-named dir we didn't stamp is never treated as ours."""
        home, project, source_root = env
        write_skill(source_root, "alpha")
        theirs = home / ".claude" / "skills" / "alpha"
        theirs.mkdir(parents=True)
        (theirs / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: the user's own\n---\nbody\n"
        )

        assert state_of(env, "alpha") is SkillState.LOCALLY_MODIFIED

    def test_local_edit_wins_over_source_drift(self, env):
        """Both stale and edited classifies as locally-modified, not update."""
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        (source_root / "alpha" / "reference.md").write_text("v2 reference\n")
        (home / ".claude" / "skills" / "alpha" / "reference.md").write_text("edited\n")

        assert state_of(env, "alpha") is SkillState.LOCALLY_MODIFIED

    def test_status_needs_no_network(self, env, monkeypatch):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)

        def no_sockets(*args, **kwargs):
            raise AssertionError("status attempted network access")

        monkeypatch.setattr(socket, "socket", no_sockets)

        assert state_of(env, "alpha") is SkillState.UP_TO_DATE


class TestInstallIdempotency:
    def test_second_install_is_a_reported_byte_identical_noop(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        installed = home / ".claude" / "skills" / "alpha"
        before = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in installed.rglob("*")
            if path.is_file()
        }

        result = run(install, env)

        assert result.ok is True
        assert result.installed == []
        assert [s.name for s in result.up_to_date] == ["alpha"]
        after = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in installed.rglob("*")
            if path.is_file()
        }
        assert after == before

    def test_stale_install_is_skipped_not_overwritten(self, env):
        """Install never updates in place; that is the update verb's job."""
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        (source_root / "alpha" / "reference.md").write_text("v2 reference\n")

        result = run(install, env)

        assert result.installed == []
        assert result.up_to_date == []
        assert [s.name for s in result.skipped] == ["alpha"]
        installed_reference = home / ".claude" / "skills" / "alpha" / "reference.md"
        assert installed_reference.read_text() == "reference for alpha\n"
