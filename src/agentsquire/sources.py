"""Skill acquisition sources.

The install/status/update/uninstall pipeline consumes the ``SkillSource``
seam — list skills, materialize one — so new acquisition mechanisms (e.g. a
whitelisted remote repository) can be added without changing verb signatures.
Bundled consumer package data is the launch implementation.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from agentsquire.hashing import skill_content_hash

# Pyproject entry-point group a consumer may register under to mark itself
# skill-carrying, reserved for a future environment-wide listing. Registering
# is optional and nothing reads it at launch: no verb changes behaviour.
ENTRY_POINT_GROUP = "agentsquire.skills"


@dataclass(frozen=True)
class SourceSkill:
    """One skill a source can provide: its name and content hash."""

    name: str
    content_hash: str


@runtime_checkable
class SkillSource(Protocol):
    """Where skills come from: list them, materialize one to a directory."""

    def list_skills(self) -> list[SourceSkill]: ...

    def materialize(self, name: str):
        """Context manager yielding a filesystem Path to the named skill dir."""
        ...


class DirectorySource:
    """Skills laid out as subdirectories of a plain local directory."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def root_exists(self) -> bool:
        return self.root.is_dir()

    def list_skills(self) -> list[SourceSkill]:
        return [
            SourceSkill(name=entry.name, content_hash=skill_content_hash(entry))
            for entry in sorted(self.root.iterdir())
            if entry.is_dir()
        ]

    @contextmanager
    def materialize(self, name: str) -> Iterator[Path]:
        skill_dir = self.root / name
        if not skill_dir.is_dir():
            raise KeyError(name)
        yield skill_dir


class BundledPackageDataSource:
    """Skills shipped as package data inside an installed consumer package.

    Backed by importlib.resources, so it works from an installed wheel with no
    source checkout; zip-served packages are extracted to a temp dir on
    materialize.
    """

    def __init__(self, package: str, resource_path: str = "skills"):
        self.package = package
        self.resource_path = resource_path

    def _root(self):
        traversable = resources.files(self.package)
        for part in self.resource_path.split("/"):
            traversable = traversable.joinpath(part)
        return traversable

    def list_skills(self) -> list[SourceSkill]:
        skills = []
        for entry in self._root().iterdir():
            if entry.is_dir():
                with self._materialized(entry) as path:
                    skills.append(
                        SourceSkill(name=entry.name, content_hash=skill_content_hash(path))
                    )
        return sorted(skills, key=lambda skill: skill.name)

    @contextmanager
    def materialize(self, name: str) -> Iterator[Path]:
        for entry in self._root().iterdir():
            if entry.name == name and entry.is_dir():
                with self._materialized(entry) as path:
                    yield path
                return
        raise KeyError(name)

    @contextmanager
    def _materialized(self, traversable) -> Iterator[Path]:
        if isinstance(traversable, Path):
            yield traversable
            return
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / traversable.name
            _copy_traversable(traversable, target)
            yield target


class DuplicateSkillError(Exception):
    """A skill name is provided by more than one member of a UnionSource.

    A collision across roots is always a packaging mistake, never a legitimate
    override — so it is a hard error naming the colliding skill and both roots,
    never namespaced or silently first-wins.
    """


def _source_label(source) -> str:
    """Best-effort human identifier for a source's backing root."""
    root = getattr(source, "root", None)
    if root is not None:
        return str(root)
    package = getattr(source, "package", None)
    if package is not None:
        resource = getattr(source, "resource_path", "") or ""
        return f"{package}/{resource}".rstrip("/")
    return repr(source)


class UnionSource:
    """Disjoint N-root merge of member sources over the ``SkillSource`` seam.

    ``list_skills()`` returns the union of the members' skills, each carrying
    the content hash its owning member reports; ``materialize(name)`` delegates
    to the member that provides that name. Roots are disjoint by construction —
    a name in more than one member raises ``DuplicateSkillError``, never an
    override.
    """

    def __init__(self, sources: list):
        self.sources = list(sources)

    def _owners(self) -> dict:
        """Map each skill name to the (source, SourceSkill) that provides it.

        Raises ``DuplicateSkillError`` naming the colliding skill and both
        owning roots if any name is provided by more than one member.
        """
        owners: dict[str, tuple] = {}
        for source in self.sources:
            for skill in source.list_skills():
                if skill.name in owners:
                    first, _ = owners[skill.name]
                    raise DuplicateSkillError(
                        f"skill {skill.name!r} is provided by more than one root: "
                        f"{_source_label(first)} and {_source_label(source)}"
                    )
                owners[skill.name] = (source, skill)
        return owners

    def list_skills(self) -> list[SourceSkill]:
        return sorted(
            (skill for _, skill in self._owners().values()),
            key=lambda skill: skill.name,
        )

    @contextmanager
    def materialize(self, name: str) -> Iterator[Path]:
        owner = self._owners().get(name)
        if owner is None:
            raise KeyError(name)
        source, _ = owner
        with source.materialize(name) as path:
            yield path


class FirstAvailableSource:
    """Resolves entirely to the first member whose backing root exists.

    Members are tried in order; the first whose ``root_exists()`` is true wins
    and every subsequent member is ignored — exactly one branch is ever live.
    This is the directory-shaped generalization of the wheel-first /
    source-fallback pattern: a packaged copy tried first, a checkout root
    second. An existing but empty root still wins (it lists zero skills); with
    no member available, ``list_skills()`` is empty and ``materialize`` raises
    ``KeyError``.
    """

    def __init__(self, sources: list):
        self.sources = list(sources)

    def _active(self):
        """The first member whose backing root exists, or None."""
        for source in self.sources:
            if source.root_exists():
                return source
        return None

    def list_skills(self) -> list[SourceSkill]:
        active = self._active()
        return active.list_skills() if active is not None else []

    @contextmanager
    def materialize(self, name: str) -> Iterator[Path]:
        active = self._active()
        if active is None:
            raise KeyError(name)
        with active.materialize(name) as path:
            yield path


def _copy_traversable(traversable, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in traversable.iterdir():
        if child.is_dir():
            _copy_traversable(child, target / child.name)
        else:
            (target / child.name).write_bytes(child.read_bytes())
