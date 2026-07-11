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
from agentsquire.stamping import StampError, read_stamp, stamped_skill_md


class SkillState(enum.Enum):
    """The four mutually exclusive states of a skill per harness x scope."""

    NOT_INSTALLED = "not-installed"
    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    LOCALLY_MODIFIED = "locally-modified"


@dataclass(frozen=True)
class SkillStatus:
    """One skill's classified state at its target path."""

    name: str
    state: SkillState
    path: Path


@dataclass(frozen=True)
class InstalledSkill:
    """One skill copied and stamped at its installed path."""

    name: str
    path: Path
    content_hash: str


@dataclass(frozen=True)
class SkippedSkill:
    """One skill a verb left untouched, and why."""

    name: str
    reason: str


@dataclass(frozen=True)
class InstallResult:
    """Per-skill outcomes of one install run; ok is False when any rejected."""

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
    A symlink (dangling or live) is likewise present-but-not-ours.
    """
    if target.is_symlink():
        # exists() follows the link and would misjudge the target — a dangling
        # link reads as absent, a live one as its destination. A symlink is
        # never ours: report it locally-modified so install/update skip it and
        # never rmtree the link (BUG-02).
        return SkillState.LOCALLY_MODIFIED
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


def _skip_reason(state: SkillState, target: Path) -> str:
    """The reason a skill was skipped, made specific when the target is a
    symlink so the remedy — remove the link, or force — is clear (BUG-02)."""
    if target.is_symlink():
        return (
            f"{state.value} (target is a symlink; remove it, "
            "or update --force to replace it)"
        )
    return state.value


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
                    SkippedSkill(name=entry.name, reason=_skip_reason(state, target))
                )
                continue
            try:
                result.installed.append(
                    _copy_and_stamp(skill_dir, target, source_package, source_version)
                )
            except StampError as error:
                result.rejected.append(_stamp_violation(entry.name, error))
    return result


def _copy_and_stamp(
    skill_dir: Path, target: Path, source_package: str, source_version: str
) -> InstalledSkill:
    content_hash = skill_content_hash(skill_dir)
    stamp = {
        "installer": "agentsquire",
        "installer_version": agentsquire.__version__,
        "source_package": source_package,
        "source_version": source_version,
        "content_hash": content_hash,
    }
    # Stamp before touching the target: an unstampable manifest raises here,
    # leaving neither a partial copy nor (on update) a removed old install.
    stamped = stamped_skill_md((skill_dir / "SKILL.md").read_text(), stamp)
    # Remove any prior entry symlink-safely: unlink a link (dangling or live)
    # rather than rmtree through it, and rmtree only a real directory (BUG-02).
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, target, symlinks=False)
    (target / "SKILL.md").write_text(stamped)
    return InstalledSkill(name=target.name, path=target, content_hash=content_hash)


def _stamp_violation(name: str, error: StampError) -> SkillViolation:
    return SkillViolation(skill=name, rule="unstampable", message=f"{name}: {error}")


@dataclass(frozen=True)
class UpdateResult:
    """Per-skill outcomes of one update run; ok is False when any rejected."""

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
            result.skipped.append(
                SkippedSkill(name=entry.name, reason=_skip_reason(state, target))
            )
            continue
        with source.materialize(entry.name) as skill_dir:
            violations = validate_skill_dir(skill_dir)
            if violations:
                result.rejected.extend(violations)
                continue
            try:
                result.updated.append(
                    _copy_and_stamp(skill_dir, target, source_package, source_version)
                )
            except StampError as error:
                result.rejected.append(_stamp_violation(entry.name, error))
    return result


@dataclass(frozen=True)
class RemovedSkill:
    """One our-stamped skill directory that uninstall removed."""

    name: str
    path: Path


@dataclass(frozen=True)
class UninstallResult:
    """Per-skill outcomes of one uninstall run."""

    removed: list[RemovedSkill] = field(default_factory=list)
    skipped: list[SkippedSkill] = field(default_factory=list)


def uninstall(
    source: SkillSource,
    backend: HarnessBackend,
    *,
    scope: str,
    home: Path,
    project: Path,
    source_package: str,
) -> UninstallResult:
    """Remove installed skill dirs whose stamp names us and the consumer.

    A same-named directory that is unstamped, or stamped by a different
    installer or source package, is left in place with the reason recorded
    (REQ-13) — it is not ours to delete.
    """
    target_root = backend.skills_dir(scope, home=home, project=project)
    result = UninstallResult()
    for entry in source.list_skills():
        target = target_root / entry.name

        def skip(reason: str) -> None:
            result.skipped.append(SkippedSkill(name=entry.name, reason=reason))

        if target.is_symlink():
            # Present but not ours, and never rmtree a link: leave it (BUG-02).
            skip("target is a symlink; not removing")
            continue
        if not target.exists():
            skip("not-installed")
            continue
        manifest = target / "SKILL.md"
        stamp = read_stamp(manifest.read_text()) if manifest.is_file() else None
        if stamp is None:
            skip("no agentsquire provenance stamp; not removing")
            continue
        if stamp.get("installer") != "agentsquire":
            skip(f"stamped by installer {stamp.get('installer')!r}; not removing")
            continue
        if stamp.get("source_package") != source_package:
            skip(
                f"installed from package {stamp.get('source_package')!r},"
                f" not {source_package!r}; not removing"
            )
            continue
        shutil.rmtree(target)
        result.removed.append(RemovedSkill(name=entry.name, path=target))
    return result
