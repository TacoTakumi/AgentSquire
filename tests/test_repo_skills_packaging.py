"""agentsquire dogfoods the full Root B recipe with an empty .gitkeep (REQ-15).

agentsquire stands up a repo-level skills/ wired as Root B via the same
force-include stanza it documents for consumers, seeded with a .gitkeep so the
empty root ships and lists zero skills. developing-with-agentsquire stays in
Root A (src/agentsquire/skills); the default union lists exactly Root A, with
.gitkeep never enumerated as a skill.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agentsquire.sources import BundledPackageDataSource, default_source

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    outdir = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [
            sys.executable, "-m", "build", "--wheel", "--no-isolation",
            "--outdir", str(outdir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return next(outdir.glob("*.whl"))


def record_paths(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as zf:
        record = next(n for n in zf.namelist() if n.endswith(".dist-info/RECORD"))
        text = zf.read(record).decode()
    return {line.split(",", 1)[0] for line in text.splitlines() if line}


def test_repo_root_gitkeep_is_committed():
    out = subprocess.run(
        ["git", "ls-files", "skills/.gitkeep"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert out.stdout.strip() == "skills/.gitkeep"


def test_wheel_ships_the_empty_root_b_marker(built_wheel):
    assert "agentsquire/_repo_skills/.gitkeep" in record_paths(built_wheel)


def test_default_union_lists_exactly_root_a_with_no_gitkeep():
    names = [skill.name for skill in default_source("agentsquire").list_skills()]
    assert names == ["developing-with-agentsquire"]
    assert ".gitkeep" not in names


def test_developing_skill_still_resolves_from_root_a():
    root_a = BundledPackageDataSource("agentsquire", "skills")
    assert "developing-with-agentsquire" in [s.name for s in root_a.list_skills()]
    with default_source("agentsquire").materialize(
        "developing-with-agentsquire"
    ) as path:
        assert (path / "SKILL.md").is_file()
