"""T-05 / REQ-07, REQ-10: the wheel force-includes the three canonical docs.

The `guide` command needs a single authoritative source for its pages with no
hand-maintained in-package duplicate. The build force-includes docs/api.md,
docs/harnesses.md, and README.md into the wheel under agentsquire/_docs/, and the
package source commits no copy of them. Verified by build-and-install, following
the tests/test_bundled_source.py pattern.
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Force-include maps the three sources to these packaged paths.
PACKAGED_DOCS = {
    "agentsquire/_docs/api.md": PROJECT_ROOT / "docs" / "api.md",
    "agentsquire/_docs/harnesses.md": PROJECT_ROOT / "docs" / "harnesses.md",
    "agentsquire/_docs/integration.md": PROJECT_ROOT / "README.md",
}


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    """Build the agentsquire wheel into a temp dir and hand back its path."""
    outdir = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [
            sys.executable, "-m", "build", "--wheel", "--no-isolation",
            "--outdir", str(outdir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return next(outdir.glob("*.whl"))


def _record_paths(wheel: Path) -> set[str]:
    """The path column of the wheel's dist-info RECORD."""
    with zipfile.ZipFile(wheel) as zf:
        record = next(n for n in zf.namelist() if n.endswith(".dist-info/RECORD"))
        text = zf.read(record).decode()
    return {line.split(",", 1)[0] for line in text.splitlines() if line}


def test_wheel_record_lists_the_three_packaged_docs(built_wheel):
    paths = _record_paths(built_wheel)
    for packaged in PACKAGED_DOCS:
        assert packaged in paths, f"{packaged} missing from wheel RECORD"


def test_packaged_docs_carry_their_source_bytes(built_wheel):
    with zipfile.ZipFile(built_wheel) as zf:
        for packaged, source in PACKAGED_DOCS.items():
            assert zf.read(packaged).decode() == source.read_text()


def test_no_canonical_doc_is_committed_under_the_package_source():
    out = subprocess.run(
        ["git", "ls-files", "src/agentsquire"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = out.stdout.splitlines()
    offenders = [
        p for p in tracked
        if Path(p).name in {"api.md", "harnesses.md", "integration.md"}
        or "/_docs/" in p
    ]
    assert offenders == [], f"canonical docs must live in docs/ only, not: {offenders}"
