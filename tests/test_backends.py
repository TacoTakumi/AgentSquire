"""All four launch backends and their conformance to docs/harnesses.md (REQ-04..06).

Fixture environments containing marker directories for arbitrary subsets of
harnesses must detect exactly that subset, and every backend must resolve
exactly the directories its reference-document entry records — a backticked
path resolves, an explicit "none" scope errors.
"""

import re
from pathlib import Path

import pytest

from agentsquire.harnesses import UnsupportedScopeError, default_registry

DOC = Path(__file__).parent.parent / "docs" / "harnesses.md"

# doc section heading -> backend name
HARNESSES = {
    "Claude Code": "claude-code",
    "pi": "pi",
    "Hermes": "hermes",
    "opencode": "opencode",
}

# one user-scope marker directory per harness, used to fake its presence
USER_MARKERS = {
    "claude-code": ".claude",
    "pi": ".pi",
    "hermes": ".hermes",
    "opencode": ".config/opencode",
}


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    return home, project


def doc_scope_value(harness: str, scope: str) -> str:
    """The value of the harness's scope line in docs/harnesses.md."""
    section = re.split(rf"^## {re.escape(harness)}$", DOC.read_text(), flags=re.MULTILINE)[1]
    section = section.split("\n## ")[0]
    line = re.search(rf"^\s*- {scope}: (.+)$", section, flags=re.MULTILINE)
    assert line, f"{harness}: no {scope}-scope line in the reference doc"
    return line.group(1)


def test_all_four_launch_backends_are_registered():
    assert sorted(default_registry().names()) == sorted(HARNESSES.values())


@pytest.mark.parametrize(
    "subset",
    [
        [],
        ["claude-code"],
        ["hermes"],
        ["pi", "opencode"],
        ["claude-code", "pi", "hermes", "opencode"],
    ],
    ids=lambda subset: "+".join(subset) or "none",
)
def test_detection_returns_exactly_the_present_subset(env, subset):
    home, project = env
    for name in subset:
        (home / USER_MARKERS[name]).mkdir(parents=True)

    detected = default_registry().detect(home=home, project=project)

    assert sorted(backend.name for backend in detected) == sorted(subset)


@pytest.mark.parametrize("harness,name", HARNESSES.items(), ids=HARNESSES.values())
@pytest.mark.parametrize("scope", ["user", "project"])
def test_backend_resolves_exactly_the_documented_directory(env, harness, name, scope):
    """REQ-06: doc-conformance — backticked path resolves, explicit none errors."""
    home, project = env
    (home / USER_MARKERS[name]).mkdir(parents=True)
    backend = default_registry().resolve(name, home=home, project=project)
    documented = doc_scope_value(harness, scope)

    path = re.search(r"`([^`]+)`", documented)
    if path is None:
        assert "none" in documented.lower(), (
            f"{harness}: {scope} scope has neither a path nor an explicit none"
        )
        with pytest.raises(UnsupportedScopeError, match=f"{scope}-scope"):
            backend.skills_dir(scope, home=home, project=project)
        return

    documented_path = path.group(1)
    root = home if documented_path.startswith("~/") else project
    expected = root / documented_path.removeprefix("~/").rstrip("/")

    assert backend.skills_dir(scope, home=home, project=project) == expected


def test_project_marker_dirs_also_detect(env):
    home, project = env
    (project / ".pi").mkdir()
    (project / ".opencode").mkdir()

    detected = default_registry().detect(home=home, project=project)

    assert sorted(backend.name for backend in detected) == ["opencode", "pi"]
