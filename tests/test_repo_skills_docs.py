"""Integration docs for repo-level skills, and no build-time coupling (REQ-12/14).

The consumer guide must carry the exact one-line force-include stanza mapping the
repo-root skills dir to <pkg>/_repo_skills, plus a full copyable hatch_build.py
build-hook snippet that fails the wheel build when a repo-root skill is dropped.
And agentsquire itself must ship no build-hook plugin or entry point and add no
build-system requirement to consumers - the single force-include line is the
only mandatory consumer packaging change.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"


def blocks(language: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", README.read_text(), flags=re.DOTALL)


def block_containing(language: str, marker: str) -> str:
    matches = [b for b in blocks(language) if marker in b]
    assert len(matches) == 1, (
        f"expected exactly one {language} block containing {marker!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def test_force_include_stanza_maps_repo_skills_to_the_fixed_location():
    stanza = block_containing("toml", "_repo_skills")
    data = tomllib.loads(stanza)
    mapping = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert mapping["skills"] == "your_pkg/_repo_skills"


def test_hatch_build_snippet_is_a_full_copyable_build_hook():
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface

    snippet = block_containing("python", "BuildHookInterface")
    namespace: dict = {}
    exec(compile(snippet, "<hatch_build.py>", "exec"), namespace)
    hooks = [
        value
        for value in namespace.values()
        if isinstance(value, type)
        and issubclass(value, BuildHookInterface)
        and value is not BuildHookInterface
    ]
    assert len(hooks) == 1, "snippet must define exactly one BuildHookInterface subclass"
    assert callable(getattr(hooks[0], "initialize", None))


def test_agentsquire_ships_no_build_hook_plugin_or_entry_point():
    data = tomllib.loads(PYPROJECT.read_text())
    entry_points = data["project"].get("entry-points", {})
    assert "hatch" not in entry_points  # no hatchling plugin registration
    hatch_build = data.get("tool", {}).get("hatch", {}).get("build", {})
    assert "hooks" not in hatch_build
    for target in hatch_build.get("targets", {}).values():
        assert "hooks" not in target


def test_agentsquire_adds_no_build_system_requirement_and_says_so():
    data = tomllib.loads(PYPROJECT.read_text())
    assert not any("agentsquire" in req for req in data["build-system"]["requires"])
    assert "only packaging change agentsquire requires" in README.read_text()
