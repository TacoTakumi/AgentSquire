"""T-01 / REQ-11..13: the one bundled skill is a valid, wheel-shipped skill
whose body covers every agentsquire wiring point and points at the reference."""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agentsquire.skills import load_skill, validate_skill_dir

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "src" / "agentsquire" / "skills" / "developing-with-agentsquire"
SKILL_MD = SKILL_DIR / "SKILL.md"

# REQ-13: the body must cover each wiring point. Grep-checkable tokens, one per
# point the consumer guide names.
WIRING_TOKENS = [
    "package data",          # skills-as-package-data layout
    "skills_command_group",  # the mount call
    "check_stale",           # the staleness notice hook
    "[project.scripts]",     # console entry
    "agentsquire.skills",    # entry-point marker
    "provenance",            # provenance/update (staleness) model
    "staleness",
]
# ...and it must point at the full reference rather than duplicate it.
DOCS_POINTER_TOKENS = ["squire guide", "docs/"]


def test_skill_dir_is_structurally_valid():
    # REQ-11: validate_skill_dir reports no violations.
    assert validate_skill_dir(SKILL_DIR) == []


def test_frontmatter_name_matches_directory():
    # REQ-11: frontmatter name is developing-with-agentsquire.
    assert load_skill(SKILL_DIR).name == "developing-with-agentsquire"


def test_body_covers_every_wiring_point():
    # REQ-13: token checklist over the body.
    body = SKILL_MD.read_text()
    missing = [token for token in WIRING_TOKENS if token not in body]
    assert not missing, f"SKILL.md body is missing wiring tokens: {missing}"


def test_body_points_to_guide_or_docs():
    # REQ-13: a pointer to the full reference, not a duplicate of it.
    body = SKILL_MD.read_text()
    assert any(token in body for token in DOCS_POINTER_TOKENS)


@pytest.fixture(scope="module")
def wheel_record(tmp_path_factory):
    """Build the real agentsquire wheel and return its RECORD text (REQ-12)."""
    outdir = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(outdir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    wheel = next(outdir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as zf:
        record_name = next(n for n in zf.namelist() if n.endswith(".dist-info/RECORD"))
        return zf.read(record_name).decode()


def test_bundled_skill_ships_in_the_wheel(wheel_record):
    # REQ-12: the skill's SKILL.md is listed in the built wheel's RECORD.
    assert "agentsquire/skills/developing-with-agentsquire/SKILL.md" in wheel_record
