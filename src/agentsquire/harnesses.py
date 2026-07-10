"""Harness backends and registry.

Each supported harness gets one backend recording where it keeps skills per
scope and which marker directories signal its presence. Directory values
mirror docs/harnesses.md (REQ-06) — change the document first, then the
backend. Adding harness N+1 means registering one more backend; the verbs
never change (REQ-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SCOPES = ("user", "project")


class UnknownHarnessError(Exception):
    def __init__(self, name: str, supported: list[str]):
        self.name = name
        self.supported = supported
        super().__init__(
            f"unknown harness {name!r}; supported harnesses: {', '.join(supported)}"
        )


class HarnessNotDetectedError(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"harness {name!r} is supported but not detected on this machine or in this project"
        )


class UnsupportedScopeError(Exception):
    def __init__(self, name: str, scope: str):
        self.name = name
        self.scope = scope
        super().__init__(f"harness {name!r} has no {scope}-scope skills directory")


@dataclass(frozen=True)
class HarnessBackend:
    """One harness: skill directories per scope (relative to the scope root)
    and marker directories whose presence means the harness is in use."""

    name: str
    user_skills_dir: str | None = None
    project_skills_dir: str | None = None
    user_marker_dirs: tuple[str, ...] = ()
    project_marker_dirs: tuple[str, ...] = ()

    def skills_dir(self, scope: str, *, home: Path, project: Path) -> Path:
        if scope not in SCOPES:
            raise ValueError(f"unknown scope {scope!r}; expected one of {SCOPES}")
        relative = self.user_skills_dir if scope == "user" else self.project_skills_dir
        if relative is None:
            raise UnsupportedScopeError(self.name, scope)
        root = home if scope == "user" else project
        return root / relative

    def detect(self, *, home: Path, project: Path) -> bool:
        return any((home / marker).is_dir() for marker in self.user_marker_dirs) or any(
            (project / marker).is_dir() for marker in self.project_marker_dirs
        )


class HarnessRegistry:
    def __init__(self):
        self._backends: dict[str, HarnessBackend] = {}

    def register(self, backend: HarnessBackend) -> None:
        self._backends[backend.name] = backend

    def names(self) -> list[str]:
        return list(self._backends)

    def detect(self, *, home: Path, project: Path) -> list[HarnessBackend]:
        return [
            backend
            for backend in self._backends.values()
            if backend.detect(home=home, project=project)
        ]

    def resolve(self, name: str, *, home: Path, project: Path) -> HarnessBackend:
        backend = self._backends.get(name)
        if backend is None:
            raise UnknownHarnessError(name, self.names())
        if not backend.detect(home=home, project=project):
            raise HarnessNotDetectedError(name)
        return backend


CLAUDE_CODE = HarnessBackend(
    name="claude-code",
    user_skills_dir=".claude/skills",
    project_skills_dir=".claude/skills",
    user_marker_dirs=(".claude",),
    project_marker_dirs=(".claude",),
)

PI = HarnessBackend(
    name="pi",
    user_skills_dir=".pi/agent/skills",
    project_skills_dir=".pi/skills",
    user_marker_dirs=(".pi",),
    project_marker_dirs=(".pi",),
)

# Hermes has no per-project skills directory; project scope errors (see doc).
HERMES = HarnessBackend(
    name="hermes",
    user_skills_dir=".hermes/skills",
    user_marker_dirs=(".hermes",),
)

OPENCODE = HarnessBackend(
    name="opencode",
    user_skills_dir=".config/opencode/skills",
    project_skills_dir=".opencode/skills",
    user_marker_dirs=(".config/opencode", ".opencode"),
    project_marker_dirs=(".opencode",),
)


def default_registry() -> HarnessRegistry:
    """A fresh registry with the launch backends registered."""
    registry = HarnessRegistry()
    registry.register(CLAUDE_CODE)
    registry.register(PI)
    registry.register(HERMES)
    registry.register(OPENCODE)
    return registry
