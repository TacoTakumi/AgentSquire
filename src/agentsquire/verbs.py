"""Skill lifecycle verbs, generic over sources and harness backends.

Verbs take a SkillSource and a HarnessBackend and never know about any
particular consumer or harness (REQ-05, REQ-15). Install is copy + provenance
stamp (D-05): the whole skill directory is copied — symlinks dereferenced, so
the installed tree is regular files with no references into site-packages —
and the SKILL.md frontmatter gains a ``metadata.agentsquire`` stamp recording
installer, source package, and content hash.
"""

from __future__ import annotations

import enum
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import agentsquire
from agentsquire.harnesses import HarnessBackend
from agentsquire.hashing import skill_content_hash
from agentsquire.skills import SkillViolation, validate_skill_dir
from agentsquire.sources import SkillSource, SourceSkill
from agentsquire.stamping import read_stamp, stamped_skill_md


class SkillState(enum.Enum):
    NOT_INSTALLED = "not-installed"
    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    LOCALLY_MODIFIED = "locally-modified"


@dataclass(frozen=True)
class SkillStatus:
    name: str
    state: SkillState
    path: Path


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
    up_to_date: list[SkillStatus] = field(default_factory=list)
    rejected: list[SkillViolation] = field(default_factory=list)
    skipped: list[SkippedSkill] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def _classify(entry: SourceSkill, target: Path) -> SkillState:
    """One skill's state from local hash compares only (REQ-11, no network).

    A same-named directory without our stamp, or whose content no longer
    matches its own stamped hash, is locally modified — never ours to touch.
    """
    if not target.exists():
        return SkillState.NOT_INSTALLED
    manifest = target / "SKILL.md"
    if not manifest.is_file():
        return SkillState.LOCALLY_MODIFIED
    stamp = read_stamp(manifest.read_text())
    stamped_hash = stamp.get("content_hash") if stamp else None
    if stamped_hash != skill_content_hash(target):
        return SkillState.LOCALLY_MODIFIED
    if stamped_hash != entry.content_hash:
        return SkillState.UPDATE_AVAILABLE
    return SkillState.UP_TO_DATE


def status(
    source: SkillSource,
    backend: HarnessBackend,
    *,
    scope: str,
    home: Path,
    project: Path,
) -> list[SkillStatus]:
    """Classify every source skill against the backend's scope directory."""
    target_root = backend.skills_dir(scope, home=home, project=project)
    return [
        SkillStatus(
            name=entry.name,
            state=_classify(entry, target_root / entry.name),
            path=target_root / entry.name,
        )
        for entry in source.list_skills()
    ]


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

    Idempotent: a current install is a byte-identical no-op reported as
    up-to-date (REQ-10). Invalid skills are rejected with their violations
    without stopping the run; stale or locally-modified installs are skipped,
    never overwritten — updating is the update verb's job.
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
            state = _classify(entry, target)
            if state is SkillState.UP_TO_DATE:
                result.up_to_date.append(
                    SkillStatus(name=entry.name, state=state, path=target)
                )
                continue
            if state is not SkillState.NOT_INSTALLED:
                result.skipped.append(
                    SkippedSkill(name=entry.name, reason=state.value)
                )
                continue
            result.installed.append(
                _copy_and_stamp(skill_dir, target, source_package, source_version)
            )
    return result


def _copy_and_stamp(
    skill_dir: Path, target: Path, source_package: str, source_version: str
) -> InstalledSkill:
    content_hash = skill_content_hash(skill_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
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
    return InstalledSkill(name=target.name, path=target, content_hash=content_hash)


@dataclass(frozen=True)
class UpdateResult:
    updated: list[InstalledSkill] = field(default_factory=list)
    up_to_date: list[SkillStatus] = field(default_factory=list)
    rejected: list[SkillViolation] = field(default_factory=list)
    skipped: list[SkippedSkill] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def update(
    source: SkillSource,
    backend: HarnessBackend,
    *,
    scope: str,
    home: Path,
    project: Path,
    source_package: str,
    source_version: str,
    force: bool = False,
) -> UpdateResult:
    """Re-copy and re-stamp every update-available skill (REQ-12).

    Locally-modified installs are skipped — the result names each one — and
    only an explicit force overwrites them. Not-installed skills are left to
    the install verb.
    """
    target_root = backend.skills_dir(scope, home=home, project=project)
    result = UpdateResult()
    for entry in source.list_skills():
        target = target_root / entry.name
        state = _classify(entry, target)
        if state is SkillState.UP_TO_DATE:
            result.up_to_date.append(
                SkillStatus(name=entry.name, state=state, path=target)
            )
            continue
        if state is SkillState.NOT_INSTALLED or (
            state is SkillState.LOCALLY_MODIFIED and not force
        ):
            result.skipped.append(SkippedSkill(name=entry.name, reason=state.value))
            continue
        with source.materialize(entry.name) as skill_dir:
            violations = validate_skill_dir(skill_dir)
            if violations:
                result.rejected.extend(violations)
                continue
            shutil.rmtree(target)
            result.updated.append(
                _copy_and_stamp(skill_dir, target, source_package, source_version)
            )
    return result
