"""Root B resolution: wheel _repo_skills first, else marker-walked repo skills/.

Root B is FirstAvailableSource([BundledPackageDataSource(pkg,'_repo_skills'),
DirectorySource(<repo>/skills)]) (REQ-10). The editable-checkout <repo> is found
by a marker-walk up from the package's on-disk location to the first directory
holding both pyproject.toml and a skills/ subdir (REQ-11), robust to src-layout
and flat-layout. A wheel install and an editable checkout must yield the
identical Root B skill set.
"""

import importlib
import sys
from pathlib import Path

from agentsquire.sources import find_repo_root, repo_skills_source

# Identical skill content authored into both wheel and checkout roots, so equal
# names imply equal content hashes.
SKILLS = {"gamma": "gamma body", "delta": "delta body"}


def write_skills(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, body in SKILLS.items():
        skill = root / name
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A fixture skill.\n---\n\n{body}\n"
        )


def make_importable(monkeypatch, path_entry: Path, package: str) -> None:
    monkeypatch.syspath_prepend(str(path_entry))
    monkeypatch.delitem(sys.modules, package, raising=False)
    importlib.invalidate_caches()


def build_wheel_pkg(base: Path, package: str) -> Path:
    """An installed-wheel layout: <site>/<pkg>/_repo_skills, no repo checkout."""
    pkg_dir = base / "site" / package
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    write_skills(pkg_dir / "_repo_skills")
    return base / "site"


def build_checkout_pkg(base: Path, package: str, layout: str) -> tuple[Path, Path]:
    """A checkout: <repo>/pyproject.toml + <repo>/skills, no _repo_skills.

    Returns (sys.path entry, repo root). layout is 'src' or 'flat'.
    """
    repo = base / "repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    write_skills(repo / "skills")
    if layout == "src":
        pkg_dir = repo / "src" / package
        path_entry = repo / "src"
    else:
        pkg_dir = repo / package
        path_entry = repo
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    return path_entry, repo


def sig(source) -> list[tuple[str, str]]:
    return sorted((s.name, s.content_hash) for s in source.list_skills())


def test_wheel_and_src_checkout_yield_equal_root_b(tmp_path, monkeypatch):
    whl = build_wheel_pkg(tmp_path / "w", "rootb_whl_src")
    entry, _ = build_checkout_pkg(tmp_path / "c", "rootb_co_src", "src")
    make_importable(monkeypatch, whl, "rootb_whl_src")
    make_importable(monkeypatch, entry, "rootb_co_src")

    wheel_sig = sig(repo_skills_source("rootb_whl_src"))
    checkout_sig = sig(repo_skills_source("rootb_co_src"))
    assert [n for n, _ in wheel_sig] == ["delta", "gamma"]
    assert wheel_sig == checkout_sig


def test_wheel_and_flat_checkout_yield_equal_root_b(tmp_path, monkeypatch):
    whl = build_wheel_pkg(tmp_path / "w", "rootb_whl_flat")
    entry, _ = build_checkout_pkg(tmp_path / "c", "rootb_co_flat", "flat")
    make_importable(monkeypatch, whl, "rootb_whl_flat")
    make_importable(monkeypatch, entry, "rootb_co_flat")

    assert sig(repo_skills_source("rootb_whl_flat")) == sig(
        repo_skills_source("rootb_co_flat")
    )


def test_marker_walk_finds_repo_root_src_layout(tmp_path, monkeypatch):
    entry, repo = build_checkout_pkg(tmp_path, "rootb_walk_src", "src")
    make_importable(monkeypatch, entry, "rootb_walk_src")
    assert find_repo_root("rootb_walk_src") == repo


def test_marker_walk_finds_repo_root_flat_layout(tmp_path, monkeypatch):
    entry, repo = build_checkout_pkg(tmp_path, "rootb_walk_flat", "flat")
    make_importable(monkeypatch, entry, "rootb_walk_flat")
    assert find_repo_root("rootb_walk_flat") == repo


def test_pyproject_without_skills_subdir_is_not_accepted(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    pkg_dir = repo / "rootb_nopq"
    pkg_dir.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    (pkg_dir / "__init__.py").write_text("")  # note: no repo/skills dir
    make_importable(monkeypatch, repo, "rootb_nopq")
    assert find_repo_root("rootb_nopq") is None


def test_marker_walk_finding_nothing_omits_the_checkout_branch(tmp_path, monkeypatch):
    # Wheel layout with NO _repo_skills and no checkout above: only the wheel
    # member is present, and it lists nothing.
    pkg_dir = tmp_path / "site" / "rootb_none"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    make_importable(monkeypatch, tmp_path / "site", "rootb_none")

    root_b = repo_skills_source("rootb_none")
    assert len(root_b.sources) == 1  # checkout branch omitted
    assert root_b.list_skills() == []
