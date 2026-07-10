"""The source seam: the full verb pipeline over two source implementations (REQ-18).

Every test here runs unchanged over both launch source implementations -
DirectorySource and BundledPackageDataSource - through one parameterized
fixture. The verbs consume only the SkillSource protocol, so a future
whitelisted remote-repository source slots in without changing verb code or
signatures; nothing is monkeypatched.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.hashing import STAMP_KEY
from agentsquire.skills import validate_skill_dir
from agentsquire.sources import BundledPackageDataSource, DirectorySource, SkillSource
from agentsquire.stamping import read_stamp
from agentsquire.verbs import SkillState, install, status, uninstall, update

PACKAGE = "seam_fixture_pkg"
PROVENANCE = {"source_package": "fixture-consumer", "source_version": "1.2.3"}


def write_skill(root: Path, name: str, description: str = "A fixture skill.") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nUse {name} wisely.\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")
    return skill


@pytest.fixture(params=["directory", "bundled"])
def seam(request, tmp_path, monkeypatch):
    """One skill source of each implementation, plus the root its skills are
    authored under (mutating it is 'the shipped source moved on')."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    if request.param == "directory":
        root = tmp_path / "bundle"
        root.mkdir()
        source = DirectorySource(root)
    else:
        pkg = tmp_path / "pkgroot" / PACKAGE
        root = pkg / "skills"
        root.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
        monkeypatch.delitem(sys.modules, PACKAGE, raising=False)
        source = BundledPackageDataSource(PACKAGE)
    write_skill(root, "alpha")
    return SimpleNamespace(source=source, root=root, home=home, project=project)


def verb(fn, seam, **kwargs):
    return fn(
        seam.source,
        CLAUDE_CODE,
        scope="user",
        home=seam.home,
        project=seam.project,
        **kwargs,
    )


def states(seam) -> dict[str, SkillState]:
    return {s.name: s.state for s in verb(status, seam)}


def installed_path(seam, name: str) -> Path:
    return {s.name: s.path for s in verb(status, seam)}[name]


def test_both_implementations_satisfy_the_protocol(seam):
    assert isinstance(seam.source, SkillSource)


def test_enumerate_lists_skills_with_content_hashes(seam):
    skills = seam.source.list_skills()
    assert [s.name for s in skills] == ["alpha"]
    assert all(s.content_hash for s in skills)


def test_install_copies_and_stamps(seam):
    result = verb(install, seam, **PROVENANCE)
    assert [s.name for s in result.installed] == ["alpha"]
    target = installed_path(seam, "alpha")
    assert validate_skill_dir(target) == []
    stamp = read_stamp((target / "SKILL.md").read_text())
    assert stamp["source_package"] == PROVENANCE["source_package"]
    assert (target / "reference.md").read_text() == "reference for alpha\n"


def test_status_classifies_every_state(seam):
    assert states(seam)["alpha"] is SkillState.NOT_INSTALLED
    verb(install, seam, **PROVENANCE)
    assert states(seam)["alpha"] is SkillState.UP_TO_DATE
    (seam.root / "alpha" / "reference.md").write_text("v2\n")
    assert states(seam)["alpha"] is SkillState.UPDATE_AVAILABLE
    (installed_path(seam, "alpha") / "reference.md").write_text("user edit\n")
    assert states(seam)["alpha"] is SkillState.LOCALLY_MODIFIED


def test_update_refreshes_a_stale_install(seam):
    verb(install, seam, **PROVENANCE)
    (seam.root / "alpha" / "reference.md").write_text("v2\n")
    result = verb(update, seam, **PROVENANCE)
    assert [s.name for s in result.updated] == ["alpha"]
    assert states(seam)["alpha"] is SkillState.UP_TO_DATE
    assert (installed_path(seam, "alpha") / "reference.md").read_text() == "v2\n"


def test_update_skips_a_local_edit_without_force(seam):
    verb(install, seam, **PROVENANCE)
    (installed_path(seam, "alpha") / "reference.md").write_text("user edit\n")
    (seam.root / "alpha" / "reference.md").write_text("v2\n")
    result = verb(update, seam, **PROVENANCE)
    assert [s.name for s in result.skipped] == ["alpha"]
    assert (installed_path(seam, "alpha") / "reference.md").read_text() == "user edit\n"
    forced = verb(update, seam, force=True, **PROVENANCE)
    assert [s.name for s in forced.updated] == ["alpha"]
    assert (installed_path(seam, "alpha") / "reference.md").read_text() == "v2\n"


def test_uninstall_removes_our_stamped_install(seam):
    verb(install, seam, **PROVENANCE)
    target = installed_path(seam, "alpha")
    result = verb(
        uninstall, seam, source_package=PROVENANCE["source_package"]
    )
    assert [s.name for s in result.removed] == ["alpha"]
    assert not target.exists()
    assert states(seam)["alpha"] is SkillState.NOT_INSTALLED


def test_invalid_skill_is_rejected_while_valid_ones_install(seam):
    broken = seam.root / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("no frontmatter at all\n")
    result = verb(install, seam, **PROVENANCE)
    assert [s.name for s in result.installed] == ["alpha"]
    assert result.rejected and not result.ok


def test_installed_bytes_are_identical_across_sources(tmp_path, monkeypatch):
    """The same authored skill installs to byte-identical trees through
    either source implementation - the seam adds nothing of its own."""

    def run(kind: str) -> dict[str, bytes]:
        base = tmp_path / kind
        home = base / "home"
        project = base / "project"
        home.mkdir(parents=True)
        project.mkdir()
        if kind == "directory":
            root = base / "bundle"
            root.mkdir()
            source = DirectorySource(root)
        else:
            pkg = base / "pkgroot" / PACKAGE
            root = pkg / "skills"
            root.mkdir(parents=True)
            (pkg / "__init__.py").write_text("")
            monkeypatch.syspath_prepend(str(base / "pkgroot"))
            monkeypatch.delitem(sys.modules, PACKAGE, raising=False)
            source = BundledPackageDataSource(PACKAGE)
        write_skill(root, "alpha")
        install(
            source, CLAUDE_CODE, scope="user", home=home, project=project, **PROVENANCE
        )
        return {
            str(p.relative_to(home)): p.read_bytes()
            for p in sorted(home.rglob("*"))
            if p.is_file()
        }

    trees = {kind: run(kind) for kind in ("directory", "bundled")}
    assert trees["directory"], "nothing installed; comparison vacuous"
    assert trees["directory"] == trees["bundled"]
