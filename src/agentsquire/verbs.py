"""Skill lifecycle verbs, generic over sources and harness backends.

Verbs take a SkillSource and a HarnessBackend and never know about any
particular consumer or harness (REQ-05, REQ-15). Install is copy + provenance
stamp (D-05): the whole skill directory is copied — symlinks dereferenced, so
the installed tree is regular files with no references into site-packages —
and the SKILL.md frontmatter gains a ``metadata.agentsquire`` stamp recording
installer, source package, and content hash.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import agentsquire
from agentsquire.harnesses import HarnessBackend
from agentsquire.hashing import skill_content_hash
from agentsquire.skills import SkillViolation, validate_skill_dir
from agentsquire.sources import SkillSource
from agentsquire.stamping import stamped_skill_md


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    path: Path
    content_hash: str


@dataclass(frozen=True)
class SkippedSkill:
    name: str
    reason: str


@dataclass(frozen=True)
class InstallResult:
    installed: list[InstalledSkill] = field(default_factory=list)
    rejected: list[SkillViolation] = field(default_factory=list)
    skipped: list[SkippedSkill] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def install(
    source: SkillSource,
    backend: HarnessBackend,
    *,
    scope: str,
    home: Path,
    project: Path,
    source_package: str,
    source_version: str,
) -> InstallResult:
    """Copy every valid skill in the source into the backend's scope directory.

    Invalid skills are rejected with their violations without stopping the
    run; already-present skill directories are skipped, never overwritten.
    """
    target_root = backend.skills_dir(scope, home=home, project=project)
    result = InstallResult()
    for entry in source.list_skills():
        with source.materialize(entry.name) as skill_dir:
            violations = validate_skill_dir(skill_dir)
            if violations:
                result.rejected.extend(violations)
                continue
            target = target_root / entry.name
            if target.exists():
                result.skipped.append(
                    SkippedSkill(name=entry.name, reason="already installed")
                )
                continue
            content_hash = skill_content_hash(skill_dir)
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_dir, target, symlinks=False)
            stamp = {
                "installer": "agentsquire",
                "installer_version": agentsquire.__version__,
                "source_package": source_package,
                "source_version": source_version,
                "content_hash": content_hash,
            }
            manifest = target / "SKILL.md"
            manifest.write_text(stamped_skill_md(manifest.read_text(), stamp))
            result.installed.append(
                InstalledSkill(name=entry.name, path=target, content_hash=content_hash)
            )
    return result
