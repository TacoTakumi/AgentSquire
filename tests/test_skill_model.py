from pathlib import Path

import pytest

from agentsquire.skills import (
    InvalidSkillError,
    Skill,
    load_skill,
    validate_skill_dir,
)


def frontmatter(name=None, description=None):
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines += ["---", "", "# Instructions", "", "Do the thing."]
    return "\n".join(lines)


def write_skill(root: Path, dirname: str, body: str) -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(body)
    return skill_dir


def test_valid_skill_has_no_violations_and_loads(tmp_path):
    skill_dir = write_skill(
        tmp_path, "awiki-search", frontmatter("awiki-search", "Search the wiki.")
    )

    assert validate_skill_dir(skill_dir) == []

    skill = load_skill(skill_dir)
    assert isinstance(skill, Skill)
    assert skill.name == "awiki-search"
    assert skill.description == "Search the wiki."
    assert skill.path == skill_dir


def test_missing_skill_md(tmp_path):
    skill_dir = tmp_path / "no-manifest"
    skill_dir.mkdir()

    violations = validate_skill_dir(skill_dir)

    assert [v.rule for v in violations] == ["missing-skill-md"]
    assert violations[0].skill == "no-manifest"


def test_missing_frontmatter(tmp_path):
    skill_dir = write_skill(tmp_path, "bare", "# Just a heading, no frontmatter\n")

    violations = validate_skill_dir(skill_dir)

    assert [v.rule for v in violations] == ["invalid-frontmatter"]
    assert violations[0].skill == "bare"


def test_missing_name(tmp_path):
    skill_dir = write_skill(
        tmp_path, "unnamed", frontmatter(description="Does something.")
    )

    violations = validate_skill_dir(skill_dir)

    assert [v.rule for v in violations] == ["missing-name"]


def test_name_not_matching_directory(tmp_path):
    skill_dir = write_skill(
        tmp_path, "actual-dir", frontmatter("other-name", "Does something.")
    )

    violations = validate_skill_dir(skill_dir)

    assert [v.rule for v in violations] == ["name-mismatch"]
    assert violations[0].skill == "actual-dir"


def test_missing_description(tmp_path):
    skill_dir = write_skill(tmp_path, "quiet", frontmatter(name="quiet"))

    violations = validate_skill_dir(skill_dir)

    assert [v.rule for v in violations] == ["missing-description"]


def test_multiple_violations_all_reported(tmp_path):
    skill_dir = write_skill(tmp_path, "broken", frontmatter(name="wrong-name"))

    rules = {v.rule for v in validate_skill_dir(skill_dir)}

    assert rules == {"name-mismatch", "missing-description"}


def test_violation_message_names_skill_and_rule(tmp_path):
    skill_dir = write_skill(
        tmp_path, "actual-dir", frontmatter("other-name", "Does something.")
    )

    violation = validate_skill_dir(skill_dir)[0]

    assert "actual-dir" in violation.message
    assert violation.skill == "actual-dir"
    assert violation.rule


def test_load_skill_raises_on_invalid(tmp_path):
    skill_dir = write_skill(tmp_path, "broken", frontmatter(name="wrong-name"))

    with pytest.raises(InvalidSkillError) as excinfo:
        load_skill(skill_dir)

    rules = {v.rule for v in excinfo.value.violations}
    assert "name-mismatch" in rules
    assert all(v.skill == "broken" for v in excinfo.value.violations)


def test_fixture_set_classified_correctly(tmp_path):
    valid = {
        write_skill(tmp_path, "good-one", frontmatter("good-one", "First.")),
        write_skill(tmp_path, "good-two", frontmatter("good-two", "Second.")),
    }
    invalid = {
        write_skill(tmp_path, "bad-name", frontmatter("nope", "Mismatched.")),
        write_skill(tmp_path, "bad-empty", "no frontmatter here\n"),
    }
    missing = tmp_path / "bad-missing"
    missing.mkdir()
    invalid.add(missing)

    for skill_dir in valid:
        assert validate_skill_dir(skill_dir) == []
    for skill_dir in invalid:
        assert validate_skill_dir(skill_dir) != []
