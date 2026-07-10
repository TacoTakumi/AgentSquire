"""Optional entry-point marker (REQ-20).

The library names a pyproject entry-point group consumers may register under
to mark themselves skill-carrying (reserved for a future environment-wide
listing). Registration is one line of metadata and no verb reads it: a
registered fixture consumer behaves byte-identically to an unregistered one
across install / status / update / uninstall.
"""

import importlib.metadata
import sys
from pathlib import Path

import pytest

import agentsquire as sq

DOCS = Path(__file__).parent.parent / "docs" / "api.md"
PACKAGE = "fixture_consumer_pkg"
SKILL_MD = "---\nname: alpha\ndescription: A fixture skill.\n---\n\nbody\n"


def test_group_name_is_defined_and_exported():
    assert sq.ENTRY_POINT_GROUP == "agentsquire.skills"
    assert "ENTRY_POINT_GROUP" in sq.__all__


def test_docs_name_the_group_and_show_the_registration():
    text = DOCS.read_text()
    assert 'agentsquire.skills' in text
    assert '[project.entry-points."agentsquire.skills"]' in text


@pytest.fixture
def consumer_package(tmp_path, monkeypatch):
    """An importable package carrying one bundled skill as package data."""
    pkg = tmp_path / "pkgroot" / PACKAGE
    skills = pkg / "skills" / "alpha"
    skills.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skills / "SKILL.md").write_text(SKILL_MD)
    (skills / "reference.md").write_text("reference for alpha\n")
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, PACKAGE, raising=False)
    return pkg


def register(tmp_path, monkeypatch):
    """Register the fixture package under the group via distribution metadata
    (what the one-line pyproject registration becomes in an installed dist)."""
    dist = tmp_path / "distroot" / f"{PACKAGE}-1.2.3.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fixture-consumer-pkg\nVersion: 1.2.3\n"
    )
    (dist / "entry_points.txt").write_text(
        f"[agentsquire.skills]\n{PACKAGE} = {PACKAGE}\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path / "distroot"))


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run_all_verbs(pkg: Path, home: Path, project: Path) -> list:
    """Install, status, a real update, and uninstall; log verb outcomes and a
    byte snapshot of the harness tree after each step."""
    (home / ".claude").mkdir(parents=True)
    project.mkdir(parents=True)
    roots = {"home": home, "project": project}
    provenance = {"source_package": PACKAGE, "source_version": "1.2.3"}
    source = sq.BundledPackageDataSource(PACKAGE)
    backend = sq.default_registry().resolve("claude-code", **roots)
    reference = pkg / "skills" / "alpha" / "reference.md"
    original = reference.read_bytes()

    def states():
        return [
            (s.name, s.state)
            for s in sq.status(source, backend, scope="user", **roots)
        ]

    log = []
    installed = sq.install(source, backend, scope="user", **roots, **provenance)
    log.append(("install", [s.name for s in installed.installed], snapshot(home)))
    log.append(("status", states(), snapshot(home)))
    reference.write_text("v2\n")  # the shipped source moves on
    log.append(("status-after-source-change", states(), snapshot(home)))
    updated = sq.update(source, backend, scope="user", **roots, **provenance)
    log.append(("update", [s.name for s in updated.updated], snapshot(home)))
    log.append(("status-after-update", states(), snapshot(home)))
    removed = sq.uninstall(
        source, backend, scope="user", **roots, source_package=PACKAGE
    )
    log.append(("uninstall", [s.name for s in removed.removed], snapshot(home)))
    reference.write_bytes(original)  # restore for the next run
    return log


def test_registration_changes_no_behaviour(consumer_package, tmp_path, monkeypatch):
    pkg = consumer_package

    unregistered = run_all_verbs(pkg, tmp_path / "home_a", tmp_path / "project_a")

    register(tmp_path, monkeypatch)
    eps = importlib.metadata.entry_points(group=sq.ENTRY_POINT_GROUP)
    assert any(
        ep.name == PACKAGE and ep.value == PACKAGE for ep in eps
    ), "fixture registration is not visible; the comparison would be vacuous"

    registered = run_all_verbs(pkg, tmp_path / "home_b", tmp_path / "project_b")

    assert unregistered[0][1] == ["alpha"], "install did nothing; comparison vacuous"
    assert registered == unregistered
