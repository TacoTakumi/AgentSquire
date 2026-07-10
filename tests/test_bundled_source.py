import subprocess
import sys
from pathlib import Path

import pytest

from agentsquire.hashing import skill_content_hash
from agentsquire.sources import (
    BundledPackageDataSource,
    DirectorySource,
    SkillSource,
    SourceSkill,
)

SKILL_NAMES = ("alpha-skill", "beta-skill", "gamma-skill")


def write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} does things.\n---\n\n# {name}\n"
    )
    (skill_dir / "extra.txt").write_text(f"payload for {name}\n")
    return skill_dir


PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "fixture-consumer"
version = "1.2.3"

[tool.hatch.build.targets.wheel]
packages = ["src/fixture_consumer"]
"""


@pytest.fixture(scope="session")
def installed_consumer(tmp_path_factory):
    """Build a consumer wheel bundling three skills and pip-install it --target."""
    root = tmp_path_factory.mktemp("consumer")
    project = root / "fixture-consumer"
    package = project / "src" / "fixture_consumer"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    skills_src = package / "skills"
    for name in SKILL_NAMES:
        write_skill(skills_src, name)
    (project / "pyproject.toml").write_text(PYPROJECT)

    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    wheel = next((project / "dist").glob("*.whl"))

    site = root / "site"
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--no-deps", "--no-index", "--target", str(site), str(wheel),
        ],
        check=True,
        capture_output=True,
    )
    sys.path.insert(0, str(site))
    yield {"skills_src": skills_src}
    sys.path.remove(str(site))


def test_bundled_source_enumerates_exactly_the_bundled_skills(installed_consumer):
    source = BundledPackageDataSource("fixture_consumer", "skills")

    skills = source.list_skills()

    assert sorted(s.name for s in skills) == sorted(SKILL_NAMES)
    assert all(isinstance(s, SourceSkill) for s in skills)


def test_bundled_source_hashes_match_bundled_content(installed_consumer):
    source = BundledPackageDataSource("fixture_consumer", "skills")

    by_name = {s.name: s for s in source.list_skills()}

    for name in SKILL_NAMES:
        expected = skill_content_hash(installed_consumer["skills_src"] / name)
        assert by_name[name].content_hash == expected


def test_bundled_source_materializes_a_skill_directory(installed_consumer):
    source = BundledPackageDataSource("fixture_consumer", "skills")
    listed = {s.name: s for s in source.list_skills()}

    with source.materialize("beta-skill") as path:
        assert (path / "SKILL.md").is_file()
        assert (path / "extra.txt").read_text() == "payload for beta-skill\n"
        assert skill_content_hash(path) == listed["beta-skill"].content_hash


def test_bundled_source_materialize_unknown_skill_raises(installed_consumer):
    source = BundledPackageDataSource("fixture_consumer", "skills")

    with pytest.raises(KeyError):
        with source.materialize("no-such-skill"):
            pass


def test_installed_wheel_hot_path_makes_no_copy(installed_consumer, tmp_path, monkeypatch):
    """REQ-09: an on-disk installed wheel serves the real package-data paths;
    list_skills, materialize, and the status verb never create a temp copy.
    Only zip-served or namespace-package sources materialize to a temp dir."""
    import importlib

    import agentsquire.sources as sources_module
    from agentsquire.harnesses import CLAUDE_CODE
    from agentsquire.verbs import status

    calls = []
    real_temporary_directory = sources_module.tempfile.TemporaryDirectory

    def recording(*args, **kwargs):
        calls.append((args, kwargs))
        return real_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(sources_module.tempfile, "TemporaryDirectory", recording)

    source = BundledPackageDataSource("fixture_consumer", "skills")
    installed_pkg = Path(importlib.import_module("fixture_consumer").__file__).parent

    skills = source.list_skills()
    assert sorted(s.name for s in skills) == sorted(SKILL_NAMES)

    with source.materialize("alpha-skill") as path:
        assert path == installed_pkg / "skills" / "alpha-skill"

    home, project = tmp_path / "home", tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    statuses = status(source, CLAUDE_CODE, scope="user", home=home, project=project)
    assert sorted(s.name for s in statuses) == sorted(SKILL_NAMES)

    assert calls == []


def test_directory_source_implements_the_same_seam(tmp_path):
    for name in ("alpha-skill", "beta-skill"):
        write_skill(tmp_path, name)

    source = DirectorySource(tmp_path)

    assert isinstance(source, SkillSource)
    assert isinstance(BundledPackageDataSource("fixture_consumer", "skills"), SkillSource)

    skills = {s.name: s for s in source.list_skills()}
    assert sorted(skills) == ["alpha-skill", "beta-skill"]

    with source.materialize("alpha-skill") as path:
        assert skill_content_hash(path) == skills["alpha-skill"].content_hash


def test_directory_source_ignores_plain_files(tmp_path):
    write_skill(tmp_path, "alpha-skill")
    (tmp_path / "README.md").write_text("not a skill\n")

    names = [s.name for s in DirectorySource(tmp_path).list_skills()]

    assert names == ["alpha-skill"]
