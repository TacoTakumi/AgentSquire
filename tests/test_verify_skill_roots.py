"""Public verify_skill_roots(package) disjointness check (REQ-13).

agentsquire ships an importable verify_skill_roots(package) that asserts a
package's two skill roots are disjoint: silent when disjoint, raising
DuplicateSkillError naming the collision otherwise. A consumer adds it to its
test suite in one line, so a colliding root is caught in CI - running in the
normal env where agentsquire is already a runtime dep, protecting editable mode.
"""

import importlib
import sys
from pathlib import Path

import pytest

import agentsquire
from agentsquire import DuplicateSkillError, verify_skill_roots

SKILL = "---\nname: {name}\ndescription: A fixture skill.\n---\n\n{name} body\n"


def write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL.format(name=name))


def make_pkg(base, package, monkeypatch, root_a, root_b):
    pkg = base / "site" / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n')
    for name in root_a:
        write_skill(pkg / "skills", name)
    for name in root_b:
        write_skill(pkg / "_repo_skills", name)
    monkeypatch.syspath_prepend(str(base / "site"))
    monkeypatch.delitem(sys.modules, package, raising=False)
    importlib.invalidate_caches()
    return package


def test_verify_skill_roots_is_importable_from_package():
    assert agentsquire.verify_skill_roots is verify_skill_roots
    assert callable(verify_skill_roots)


def test_passes_silently_on_disjoint_roots(tmp_path, monkeypatch):
    pkg = make_pkg(tmp_path, "vsr_ok", monkeypatch, ("alpha", "beta"), ("gamma",))
    assert verify_skill_roots(pkg) is None


def test_raises_naming_the_collision_on_colliding_roots(tmp_path, monkeypatch):
    pkg = make_pkg(tmp_path, "vsr_clash", monkeypatch, ("clash",), ("clash",))
    with pytest.raises(DuplicateSkillError) as excinfo:
        verify_skill_roots(pkg)
    message = str(excinfo.value)
    assert "clash" in message
    assert f"{pkg}/skills" in message
    assert f"{pkg}/_repo_skills" in message
