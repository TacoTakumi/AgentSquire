"""Install verb: copy + provenance stamp, per-skill validation (REQ-07/08/14/19).

Installs copy the skill directory from a source into the backend-resolved
directory for the chosen scope. The installed tree is regular files only,
byte-identical to the source except a provenance stamp in the SKILL.md
frontmatter metadata map. Invalid skills are rejected with their violations
while valid skills in the same run still install.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from agentsquire import __version__
from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.hashing import STAMP_KEY, skill_content_hash
from agentsquire.skills import validate_skill_dir
from agentsquire.sources import DirectorySource
from agentsquire.verbs import install

PROVENANCE = {"source_package": "fixture-consumer", "source_version": "1.2.3"}


def write_skill(root: Path, name: str, description: str = "A fixture skill.") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nUse {name} wisely.\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")
    docs = skill / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("nested notes\n")
    return skill


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    source_root = tmp_path / "bundle"
    for directory in (home, project, source_root):
        directory.mkdir()
    return home, project, source_root


def do_install(env, scope="user", **kwargs):
    home, project, source_root = env
    return install(
        DirectorySource(source_root),
        CLAUDE_CODE,
        scope=scope,
        home=home,
        project=project,
        **PROVENANCE,
        **kwargs,
    )


def frontmatter_and_body(path: Path) -> tuple[dict, str]:
    parts = path.read_text().split("---", 2)
    return yaml.safe_load(parts[1]), parts[2]


class TestCopy:
    def test_installed_tree_is_regular_files_only(self, env):
        home, project, source_root = env
        skill = write_skill(source_root, "alpha")
        (skill / "link.md").symlink_to(skill / "reference.md")

        result = do_install(env)

        assert [s.name for s in result.installed] == ["alpha"]
        installed = home / ".claude" / "skills" / "alpha"
        entries = list(installed.rglob("*"))
        assert entries, "installed tree is empty"
        for entry in entries:
            assert not entry.is_symlink(), f"{entry} is a symlink"
            assert entry.is_file() or entry.is_dir()
        assert (installed / "link.md").read_text() == "reference for alpha\n"

    def test_byte_identical_to_source_except_the_stamp(self, env):
        home, project, source_root = env
        source = write_skill(source_root, "alpha")

        do_install(env)

        installed = home / ".claude" / "skills" / "alpha"
        for src_file in sorted(p for p in source.rglob("*") if p.is_file()):
            rel = src_file.relative_to(source)
            if rel.as_posix() == "SKILL.md":
                continue
            assert (installed / rel).read_bytes() == src_file.read_bytes()
        src_fm, src_body = frontmatter_and_body(source / "SKILL.md")
        inst_fm, inst_body = frontmatter_and_body(installed / "SKILL.md")
        assert inst_body == src_body
        inst_fm.get("metadata", {}).pop(STAMP_KEY, None)
        if not inst_fm.get("metadata") and "metadata" not in src_fm:
            inst_fm.pop("metadata", None)
        assert inst_fm == src_fm

    def test_installed_skill_survives_source_removal(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        do_install(env)

        shutil.rmtree(source_root)

        installed = home / ".claude" / "skills" / "alpha"
        assert (installed / "SKILL.md").read_text()
        assert (installed / "docs" / "notes.md").read_text() == "nested notes\n"

    def test_existing_install_is_not_overwritten(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")
        do_install(env)
        marker = home / ".claude" / "skills" / "alpha" / "reference.md"
        marker.write_text("user edited this\n")

        result = do_install(env)

        assert result.installed == []
        assert [s.name for s in result.skipped] == ["alpha"]
        assert marker.read_text() == "user edited this\n"


class TestStamp:
    def test_stamp_carries_all_five_provenance_fields(self, env):
        home, project, source_root = env
        source = write_skill(source_root, "alpha")
        source_hash = skill_content_hash(source)

        do_install(env)

        fm, _ = frontmatter_and_body(home / ".claude" / "skills" / "alpha" / "SKILL.md")
        assert fm["metadata"][STAMP_KEY] == {
            "installer": "agentsquire",
            "installer_version": __version__,
            "source_package": "fixture-consumer",
            "source_version": "1.2.3",
            "content_hash": source_hash,
        }

    def test_installed_copy_hashes_back_to_its_stamped_value(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        result = do_install(env)

        installed = home / ".claude" / "skills" / "alpha"
        assert skill_content_hash(installed) == result.installed[0].content_hash

    def test_stamped_skill_md_still_passes_spec_validation(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        do_install(env)

        installed = home / ".claude" / "skills" / "alpha"
        assert validate_skill_dir(installed) == []
        fm, _ = frontmatter_and_body(installed / "SKILL.md")
        assert fm["name"] == "alpha"
        assert fm["description"] == "A fixture skill."

    def test_stamp_merges_into_existing_metadata_map(self, env):
        home, project, source_root = env
        skill = source_root / "alpha"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: alpha\n"
            "description: Has metadata already.\n"
            "metadata:\n"
            "  author: someone\n"
            "---\n\nbody\n"
        )

        result = do_install(env)

        assert [s.name for s in result.installed] == ["alpha"]
        fm, _ = frontmatter_and_body(home / ".claude" / "skills" / "alpha" / "SKILL.md")
        assert fm["metadata"]["author"] == "someone"
        assert fm["metadata"][STAMP_KEY]["source_package"] == "fixture-consumer"


class TestScope:
    def test_user_scope_writes_to_the_user_directory(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        do_install(env, scope="user")

        assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
        assert not (project / ".claude").exists()

    def test_project_scope_writes_to_the_project_directory(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        do_install(env, scope="project")

        assert (project / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
        assert not (home / ".claude").exists()


class TestValidation:
    def test_mixed_bundle_installs_valid_and_reports_each_invalid(self, env):
        home, project, source_root = env
        write_skill(source_root, "valid-one")
        write_skill(source_root, "valid-two")
        (source_root / "no-manifest").mkdir()
        mismatched = source_root / "mismatched"
        mismatched.mkdir()
        (mismatched / "SKILL.md").write_text(
            "---\nname: wrong-name\ndescription: d\n---\nbody\n"
        )

        result = do_install(env)

        assert sorted(s.name for s in result.installed) == ["valid-one", "valid-two"]
        for name in ("valid-one", "valid-two"):
            assert (home / ".claude" / "skills" / name / "SKILL.md").is_file()
        rejected = {v.skill: v.rule for v in result.rejected}
        assert rejected == {
            "no-manifest": "missing-skill-md",
            "mismatched": "name-mismatch",
        }
        assert not (home / ".claude" / "skills" / "no-manifest").exists()
        assert not (home / ".claude" / "skills" / "mismatched").exists()
        assert result.ok is False

    def test_all_valid_bundle_is_ok(self, env):
        home, project, source_root = env
        write_skill(source_root, "alpha")

        result = do_install(env)

        assert result.ok is True
        assert result.rejected == []
