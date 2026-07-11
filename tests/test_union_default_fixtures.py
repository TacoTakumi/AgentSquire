"""Synthetic two-populated-roots fixtures for the real default union (REQ-17).

The composed default_source union's disjoint-union behaviour - list, materialize
from the owning root, and the DuplicateSkillError collision path - is covered
here with synthetic packages carrying two populated, disjoint roots (a
package-data Root A and a _repo_skills Root B), so agentsquire never has to ship
a throwaway second skill just to exercise two-root behaviour.
"""

import importlib
import sys
from pathlib import Path

import pytest

from agentsquire.sources import (
    BundledPackageDataSource,
    DuplicateSkillError,
    default_source,
)

SKILL = "---\nname: {name}\ndescription: A fixture skill.\n---\n\n{body}\n"


def write_skill(root: Path, name: str, body: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL.format(name=name, body=body))
    (skill / "ref.md").write_text(f"ref for {name}\n")


def two_root_pkg(base, package, monkeypatch, root_a, root_b):
    """An importable package with populated Root A (skills/) and Root B
    (_repo_skills/) - the composed default union over two live roots."""
    pkg = base / "site" / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n')
    for name in root_a:
        write_skill(pkg / "skills", name, f"A:{name}")
    for name in root_b:
        write_skill(pkg / "_repo_skills", name, f"B:{name}")
    monkeypatch.syspath_prepend(str(base / "site"))
    monkeypatch.delitem(sys.modules, package, raising=False)
    importlib.invalidate_caches()
    return package


def test_default_union_lists_both_populated_roots_with_owning_hashes(
    tmp_path, monkeypatch
):
    pkg = two_root_pkg(
        tmp_path, "udf_list", monkeypatch, ("alpha", "beta"), ("gamma", "delta")
    )
    listed = default_source(pkg).list_skills()

    assert sorted(s.name for s in listed) == ["alpha", "beta", "delta", "gamma"]
    root_a = {s.name: s.content_hash for s in BundledPackageDataSource(pkg, "skills").list_skills()}
    root_b = {s.name: s.content_hash for s in BundledPackageDataSource(pkg, "_repo_skills").list_skills()}
    got = {s.name: s.content_hash for s in listed}
    assert got == {**root_a, **root_b}


def test_default_union_materializes_from_each_owning_root(tmp_path, monkeypatch):
    pkg = two_root_pkg(tmp_path, "udf_mat", monkeypatch, ("alpha",), ("gamma",))
    union = default_source(pkg)

    with union.materialize("alpha") as path:  # Root A owns it
        assert "A:alpha" in (path / "SKILL.md").read_text()
        assert (path / "ref.md").read_text() == "ref for alpha\n"
    with union.materialize("gamma") as path:  # Root B owns it
        assert "B:gamma" in (path / "SKILL.md").read_text()


def test_default_union_collision_across_roots_raises_duplicate(tmp_path, monkeypatch):
    pkg = two_root_pkg(tmp_path, "udf_clash", monkeypatch, ("clash",), ("clash",))
    with pytest.raises(DuplicateSkillError) as excinfo:
        default_source(pkg).list_skills()
    message = str(excinfo.value)
    assert "clash" in message
    assert f"{pkg}/skills" in message
    assert f"{pkg}/_repo_skills" in message


def test_agentsquire_ships_no_throwaway_second_skill():
    # The two-root behaviour is covered by the synthetic fixtures above, so
    # agentsquire's own shipped set stays a single real skill (REQ-17).
    names = [s.name for s in default_source("agentsquire").list_skills()]
    assert names == ["developing-with-agentsquire"]
