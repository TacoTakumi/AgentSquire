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


def _copy_traversable(traversable, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in traversable.iterdir():
        if child.is_dir():
            _copy_traversable(child, target / child.name)
        else:
            (target / child.name).write_bytes(child.read_bytes())
