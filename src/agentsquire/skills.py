"""Skill model and agentskills.io structural validation.

A skill is a directory containing a SKILL.md whose YAML frontmatter carries at
least ``name`` (equal to the directory name) and ``description``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    frontmatter: dict = field(compare=False)


@dataclass(frozen=True)
class SkillViolation:
    skill: str
    rule: str
    message: str


class InvalidSkillError(Exception):
    def __init__(self, violations: list[SkillViolation]):
        self.violations = violations
        super().__init__("; ".join(v.message for v in violations))


def _parse_frontmatter(text: str) -> dict | None:
    """Return the YAML frontmatter mapping, or None if absent/malformed."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def validate_skill_dir(path: Path) -> list[SkillViolation]:
    """Check one skill directory against the structural rules; [] means valid."""
    skill = path.name

    def violation(rule: str, message: str) -> SkillViolation:
        return SkillViolation(skill=skill, rule=rule, message=f"{skill}: {message}")

    manifest = path / "SKILL.md"
    if not manifest.is_file():
        return [violation("missing-skill-md", "no SKILL.md in skill directory")]

    frontmatter = _parse_frontmatter(manifest.read_text())
    if frontmatter is None:
        return [violation("invalid-frontmatter", "SKILL.md has no parseable YAML frontmatter")]

    violations = []
    name = frontmatter.get("name")
    if not name:
        violations.append(violation("missing-name", "frontmatter has no name"))
    elif name != skill:
        violations.append(
            violation("name-mismatch", f"frontmatter name {name!r} != directory name")
        )
    if not frontmatter.get("description"):
        violations.append(violation("missing-description", "frontmatter has no description"))
    return violations


def load_skill(path: Path) -> Skill:
    """Parse a valid skill directory into a Skill; raise InvalidSkillError otherwise."""
    violations = validate_skill_dir(path)
    if violations:
        raise InvalidSkillError(violations)
    frontmatter = _parse_frontmatter((path / "SKILL.md").read_text())
    return Skill(
        name=frontmatter["name"],
        description=frontmatter["description"],
        path=path,
        frontmatter=frontmatter,
    )
