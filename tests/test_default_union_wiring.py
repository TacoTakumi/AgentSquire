"""Two-root union is the zero-arg default; source= overrides it (REQ-18/07/08).

One default_source(package, resource_path) factory returns
UnionSource([Root A, Root B]). skills_command_group(package) with no source arg
resolves every verb through it; a two-root fixture enumerates both roots
combined. A keyword-only source= is used verbatim and the default union is never
constructed. A package with no Root B degrades to exactly Root A, unchanged.
"""

import importlib
import sys
from pathlib import Path

from click.testing import CliRunner

from agentsquire.cli import skills_command_group
from agentsquire.sources import (
    BundledPackageDataSource,
    DirectorySource,
    UnionSource,
    default_source,
)

SKILL = "---\nname: {name}\ndescription: A fixture skill.\n---\n\n{name} body\n"


def write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL.format(name=name))


def make_importable(monkeypatch, entry: Path, package: str) -> None:
    monkeypatch.syspath_prepend(str(entry))
    monkeypatch.delitem(sys.modules, package, raising=False)
    importlib.invalidate_caches()


def two_root_pkg(base, package, monkeypatch, root_a=("alpha",), root_b=("gamma",)):
    """Importable package with Root A (skills/) and Root B (_repo_skills/)."""
    pkg = base / "site" / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n')
    for name in root_a:
        write_skill(pkg / "skills", name)
    for name in root_b:
        write_skill(pkg / "_repo_skills", name)
    make_importable(monkeypatch, base / "site", package)
    return package


def root_a_only_pkg(base, package, monkeypatch, root_a=("alpha", "beta")):
    pkg = base / "site" / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n')
    for name in root_a:
        write_skill(pkg / "skills", name)
    make_importable(monkeypatch, base / "site", package)
    return package


def home_with_claude(base):
    home = base / "home"
    (home / ".claude").mkdir(parents=True)
    project = base / "project"
    project.mkdir()
    return home, project


def invoke(app, *args):
    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_default_source_is_the_union_of_both_roots(tmp_path, monkeypatch):
    pkg = two_root_pkg(tmp_path, "du_union", monkeypatch)
    src = default_source(pkg)
    assert isinstance(src, UnionSource)
    assert sorted(s.name for s in src.list_skills()) == ["alpha", "gamma"]


def test_group_with_no_source_enumerates_both_roots(tmp_path, monkeypatch):
    pkg = two_root_pkg(tmp_path, "du_group", monkeypatch)
    home, project = home_with_claude(tmp_path)
    group = skills_command_group(pkg, home=home, project=project)

    result = invoke(group, "status")
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "gamma" in result.output


def test_source_override_is_used_verbatim_and_default_not_constructed(
    tmp_path, monkeypatch
):
    pkg = two_root_pkg(tmp_path, "du_override", monkeypatch)
    home, project = home_with_claude(tmp_path)
    override_root = tmp_path / "override"
    write_skill(override_root, "solo")

    def boom(*args, **kwargs):
        raise AssertionError("default_source must not run when source= is passed")

    monkeypatch.setattr("agentsquire.cli.default_source", boom)
    group = skills_command_group(
        pkg, source=DirectorySource(override_root), home=home, project=project
    )

    result = invoke(group, "status")
    assert result.exit_code == 0, result.output
    assert "solo" in result.output
    assert "alpha" not in result.output
    assert "gamma" not in result.output


def test_no_root_b_degrades_to_exactly_root_a(tmp_path, monkeypatch):
    pkg = root_a_only_pkg(tmp_path, "du_roota", monkeypatch)
    union = default_source(pkg)
    root_a = BundledPackageDataSource(pkg, "skills")

    got = sorted((s.name, s.content_hash) for s in union.list_skills())
    want = sorted((s.name, s.content_hash) for s in root_a.list_skills())
    assert got == want
    assert [name for name, _ in got] == ["alpha", "beta"]
