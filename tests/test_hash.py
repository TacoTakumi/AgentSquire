from pathlib import Path

import yaml

from agentsquire.hashing import STAMP_KEY, skill_content_hash


def write_skill(root: Path, dirname: str, files: dict[str, str]) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir()
    for relpath, content in files.items():
        target = skill_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return skill_dir


SKILL_MD = """\
---
name: fixture-skill
description: A fixture.
---

# Instructions

Do the thing.
"""

FILES = {
    "SKILL.md": SKILL_MD,
    "helper.py": "print('hi')\n",
    "references/notes.md": "deep detail\n",
}


def stamp(skill_dir: Path) -> None:
    """Simulate an install stamp: inject the provenance block into frontmatter."""
    text = (skill_dir / "SKILL.md").read_text()
    _, fm_text, body = text.split("---", 2)
    fm = yaml.safe_load(fm_text)
    fm.setdefault("metadata", {})[STAMP_KEY] = {
        "installer": "agentsquire",
        "installer-version": "0.1.0",
        "source": "awiki",
        "source-version": "1.2.3",
        "content-hash": "sha256:placeholder",
    }
    (skill_dir / "SKILL.md").write_text(f"---\n{yaml.safe_dump(fm)}---{body}")


def test_stable_across_runs(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    assert skill_content_hash(skill_dir) == skill_content_hash(skill_dir)


def test_stable_across_creation_order(tmp_path):
    forward = write_skill(tmp_path, "one", FILES)
    reversed_files = dict(reversed(list(FILES.items())))
    backward = write_skill(tmp_path, "two", reversed_files)
    assert skill_content_hash(forward) == skill_content_hash(backward)


def test_hash_format(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    assert skill_content_hash(skill_dir).startswith("sha256:")


def test_stamped_copy_hashes_to_unstamped_value(tmp_path):
    original = write_skill(tmp_path, "original", FILES)
    installed = write_skill(tmp_path, "installed", FILES)
    stamp(installed)

    assert skill_content_hash(installed) == skill_content_hash(original)


def test_changing_any_single_file_changes_hash(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    baseline = skill_content_hash(skill_dir)

    for relpath in FILES:
        target = skill_dir / relpath
        unmodified = target.read_text()
        target.write_text(unmodified + "\nmutated\n")
        assert skill_content_hash(skill_dir) != baseline, f"{relpath} change missed"
        target.write_text(unmodified)

    assert skill_content_hash(skill_dir) == baseline


def test_adding_a_file_changes_hash(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    baseline = skill_content_hash(skill_dir)

    (skill_dir / "extra.txt").write_text("new\n")

    assert skill_content_hash(skill_dir) != baseline


def test_renaming_a_file_changes_hash(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    baseline = skill_content_hash(skill_dir)

    (skill_dir / "helper.py").rename(skill_dir / "helper2.py")

    assert skill_content_hash(skill_dir) != baseline


def test_frontmatter_change_changes_hash(tmp_path):
    skill_dir = write_skill(tmp_path, "fixture-skill", FILES)
    baseline = skill_content_hash(skill_dir)

    (skill_dir / "SKILL.md").write_text(
        SKILL_MD.replace("A fixture.", "A different fixture.")
    )

    assert skill_content_hash(skill_dir) != baseline
