"""Full lifecycle through the plain-Python API, never the CLI (REQ-16).

Enumerate -> detect -> install -> status -> update -> uninstall runs against
fixtures using only top-level ``agentsquire`` names, and every exported name
carries a docstring.
"""

from pathlib import Path

import pytest

import agentsquire as sq


def write_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\nbody\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")
    return skill


def test_full_lifecycle_through_top_level_names(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    source_root = tmp_path / "bundle"
    for directory in (home, project, source_root):
        directory.mkdir()
    write_skill(source_root, "alpha")
    (home / ".claude").mkdir()
    roots = {"home": home, "project": project}
    provenance = {"source_package": "fixture-consumer", "source_version": "1.2.3"}

    # enumerate
    source = sq.DirectorySource(source_root)
    assert [s.name for s in source.list_skills()] == ["alpha"]

    # detect
    detected = sq.default_registry().detect(**roots)
    assert [b.name for b in detected] == ["claude-code"]
    backend = detected[0]

    # install
    installed = sq.install(source, backend, scope="user", **roots, **provenance)
    assert [s.name for s in installed.installed] == ["alpha"]

    # status
    def states():
        return {s.name: s.state for s in sq.status(source, backend, scope="user", **roots)}

    assert states()["alpha"] is sq.SkillState.UP_TO_DATE

    # update after the source moves on
    (source_root / "alpha" / "reference.md").write_text("v2\n")
    assert states()["alpha"] is sq.SkillState.UPDATE_AVAILABLE
    updated = sq.update(source, backend, scope="user", **roots, **provenance)
    assert [s.name for s in updated.updated] == ["alpha"]
    assert states()["alpha"] is sq.SkillState.UP_TO_DATE

    # uninstall
    removed = sq.uninstall(
        source, backend, scope="user", **roots, source_package="fixture-consumer"
    )
    assert [s.name for s in removed.removed] == ["alpha"]
    assert states()["alpha"] is sq.SkillState.NOT_INSTALLED


def test_the_api_is_declared():
    assert sq.__all__, "agentsquire declares no public API"


@pytest.mark.parametrize("name", sorted(getattr(sq, "__all__", [])))
def test_every_exported_name_has_a_docstring(name):
    obj = getattr(sq, name)
    if isinstance(obj, str):  # e.g. __version__-style constants documented in situ
        return
    assert getattr(obj, "__doc__", None), f"{name} has no docstring"
