"""FirstAvailableSource: exactly one live branch, wheel-or-checkout (REQ-09).

FirstAvailableSource resolves entirely to the first member whose backing root
exists, and only that member. It is the directory-shaped generalization of the
proven wheel-first / source-fallback pattern: the packaged copy is tried first,
the checkout root second, and exactly one branch is ever live.
"""

from pathlib import Path

import pytest

from agentsquire.sources import (
    DirectorySource,
    FirstAvailableSource,
    SkillSource,
)


def write_skill(root: Path, name: str, body: str = "body") -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\n{body}\n"
    )


def existing_source(tmp_path: Path, label: str, names: list[str]) -> DirectorySource:
    root = tmp_path / label
    root.mkdir()
    for name in names:
        write_skill(root, name, body=f"{label}:{name}")
    return DirectorySource(root)


def absent_source(tmp_path: Path, label: str) -> DirectorySource:
    return DirectorySource(tmp_path / label)  # never created on disk


class ExplodingSource:
    """A member that must never be consulted; any access is a test failure."""

    def root_exists(self) -> bool:  # pragma: no cover - asserts if reached
        raise AssertionError("later member was consulted")

    def list_skills(self):  # pragma: no cover - asserts if reached
        raise AssertionError("later member was consulted")

    def materialize(self, name):  # pragma: no cover - asserts if reached
        raise AssertionError("later member was consulted")


def test_first_available_satisfies_the_protocol(tmp_path):
    source = FirstAvailableSource([existing_source(tmp_path, "a", ["alpha"])])
    assert isinstance(source, SkillSource)


def test_resolves_to_the_first_member_whose_root_exists(tmp_path):
    present = existing_source(tmp_path, "present", ["beta"])
    source = FirstAvailableSource([absent_source(tmp_path, "gone"), present])

    assert [s.name for s in source.list_skills()] == ["beta"]
    with source.materialize("beta") as path:
        with present.materialize("beta") as expected:
            got = {p.name: p.read_bytes() for p in path.iterdir()}
            want = {p.name: p.read_bytes() for p in expected.iterdir()}
    assert got == want


def test_existing_but_empty_first_member_wins_and_second_never_consulted(tmp_path):
    empty = existing_source(tmp_path, "empty", [])  # exists, lists zero skills
    source = FirstAvailableSource([empty, ExplodingSource()])
    assert source.list_skills() == []


def test_all_absent_lists_zero_and_materialize_raises_keyerror(tmp_path):
    source = FirstAvailableSource(
        [absent_source(tmp_path, "one"), absent_source(tmp_path, "two")]
    )
    assert source.list_skills() == []
    with pytest.raises(KeyError):
        with source.materialize("beta"):
            pass
