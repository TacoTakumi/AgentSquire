"""Update verb: re-copy + re-stamp stale skills; never silently overwrite (REQ-12).

Update-available skills are re-copied and re-stamped, after which status
reports them up-to-date. Locally-modified installs are skipped — the result
names the skill — unless force is passed, in which case they are overwritten
and re-stamped.
"""

from pathlib import Path

import pytest

from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.hashing import skill_content_hash
from agentsquire.sources import DirectorySource
from agentsquire.stamping import read_stamp
from agentsquire.verbs import SkillState, install, status, update

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


def run(verb, env, **kwargs):
    home, project, source_root = env
    return verb(
        DirectorySource(source_root),
        CLAUDE_CODE,
        scope="user",
        home=home,
        project=project,
        **(PROVENANCE if verb in (install, update) else {}),
        **kwargs,
    )


def state_of(env, name):
    return {s.name: s.state for s in run(status, env)}[name]


def install_then_bump_source(env, name="alpha"):
    home, project, source_root = env
    write_skill(source_root, name)
    run(install, env)
    (source_root / name / "reference.md").write_text("v2 reference\n")
    return home / ".claude" / "skills" / name


class TestUpdateStale:
    def test_stale_skill_updates_then_reports_up_to_date(self, env):
        installed = install_then_bump_source(env)

        result = run(update, env)

        assert [s.name for s in result.updated] == ["alpha"]
        assert (installed / "reference.md").read_text() == "v2 reference\n"
        assert state_of(env, "alpha") is SkillState.UP_TO_DATE

    def test_update_restamps_with_the_new_content_hash(self, env):
        home, project, source_root = env
        installed = install_then_bump_source(env)

        run(update, env)

        stamp = read_stamp((installed / "SKILL.md").read_text())
        assert stamp["content_hash"] == skill_content_hash(source_root / "alpha")
        assert stamp["source_package"] == "fixture-consumer"

    def test_up_to_date_skill_is_a_byte_identical_noop(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        run(install, env)
        installed = home / ".claude" / "skills" / "alpha"
        before = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in installed.rglob("*")
            if path.is_file()
        }

        result = run(update, env)

        assert result.updated == []
        assert [s.name for s in result.up_to_date] == ["alpha"]
        after = {
            path: (path.stat().st_mtime_ns, path.read_bytes())
            for path in installed.rglob("*")
            if path.is_file()
        }
        assert after == before

    def test_not_installed_skill_is_not_installed_by_update(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        result = run(update, env)

        assert result.updated == []
        assert not (home / ".claude" / "skills" / "alpha").exists()


class TestLocallyModified:
    def test_skipped_without_force_and_files_untouched(self, env):
        installed = install_then_bump_source(env)
        (installed / "reference.md").write_text("my local edit\n")

        result = run(update, env)

        assert result.updated == []
        assert [s.name for s in result.skipped] == ["alpha"]
        assert result.skipped[0].reason == "locally-modified"
        assert (installed / "reference.md").read_text() == "my local edit\n"

    def test_force_overwrites_and_restamps(self, env):
        home, project, source_root = env
        installed = install_then_bump_source(env)
        (installed / "reference.md").write_text("my local edit\n")

        result = run(update, env, force=True)

        assert [s.name for s in result.updated] == ["alpha"]
        assert (installed / "reference.md").read_text() == "v2 reference\n"
        stamp = read_stamp((installed / "SKILL.md").read_text())
        assert stamp["content_hash"] == skill_content_hash(source_root / "alpha")
        assert state_of(env, "alpha") is SkillState.UP_TO_DATE


class TestValidation:
    def test_invalid_new_source_version_is_rejected_and_install_kept(self, env):
        home, project, source_root = env
        installed = install_then_bump_source(env)
        (source_root / "alpha" / "SKILL.md").write_text(
            "---\nname: wrong-name\ndescription: d\n---\nbody\n"
        )

        result = run(update, env)

        assert result.updated == []
        assert [v.skill for v in result.rejected] == ["alpha"]
        assert result.ok is False
        assert (installed / "reference.md").read_text() == "reference for alpha\n"

    def test_unstampable_new_version_is_rejected_and_old_install_kept(self, env):
        """A new version that is valid but cannot take the stamp (flow-style
        metadata) rejects without removing or corrupting the old install."""
        home, project, source_root = env
        installed = install_then_bump_source(env)
        (source_root / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: A fixture skill.\n"
            "metadata: {author: x}\n---\nbody\n"
        )

        result = run(update, env)

        assert result.updated == []
        assert [v.skill for v in result.rejected] == ["alpha"]
        assert result.ok is False
        assert (installed / "reference.md").read_text() == "reference for alpha\n"
        assert read_stamp((installed / "SKILL.md").read_text())  # still ours
        assert state_of(env, "alpha") is SkillState.UPDATE_AVAILABLE
