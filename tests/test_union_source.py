"""UnionSource: disjoint N-root merge over the SkillSource seam (REQ-01, REQ-02, REQ-05).

A UnionSource composes any number of member sources into one, listing the union
of their skills (each carrying its owning source's content hash) and delegating
materialize() to the member that owns a given name. Roots are disjoint by
construction; a name in two roots is a packaging mistake handled separately.
"""

from pathlib import Path

import pytest

import agentsquire
from agentsquire.sources import (
    DirectorySource,
    DuplicateSkillError,
    SkillSource,
    SourceSkill,
    UnionSource,
)


def write_skill(root: Path, name: str, body: str = "body") -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\n{body}\n"
    )


def make_source(tmp_path: Path, label: str, names: list[str]) -> DirectorySource:
    root = tmp_path / label
    root.mkdir()
    for name in names:
        write_skill(root, name, body=f"{label}:{name}")
    return DirectorySource(root)


def test_union_satisfies_the_protocol(tmp_path):
    union = UnionSource([make_source(tmp_path, "a", ["alpha"])])
    assert isinstance(union, SkillSource)


def test_lists_the_disjoint_union_with_owning_hashes(tmp_path):
    left = make_source(tmp_path, "left", ["a", "b"])
    right = make_source(tmp_path, "right", ["c", "d"])
    union = UnionSource([left, right])

    listed = union.list_skills()
    assert isinstance(listed[0], SourceSkill)
    assert sorted(s.name for s in listed) == ["a", "b", "c", "d"]

    by_name = {s.name: s.content_hash for s in listed}
    owning = {s.name: s.content_hash for s in left.list_skills() + right.list_skills()}
    assert by_name == owning


def test_materialize_delegates_to_the_owning_member(tmp_path):
    left = make_source(tmp_path, "left", ["a", "b"])
    right = make_source(tmp_path, "right", ["c", "d"])
    union = UnionSource([left, right])

    with union.materialize("c") as path:
        with right.materialize("c") as expected:
            got = {p.name: p.read_bytes() for p in path.iterdir()}
            want = {p.name: p.read_bytes() for p in expected.iterdir()}
    assert got == want


def test_materialize_unknown_name_raises_keyerror(tmp_path):
    union = UnionSource(
        [make_source(tmp_path, "left", ["a"]), make_source(tmp_path, "right", ["b"])]
    )
    with pytest.raises(KeyError):
        with union.materialize("nope"):
            pass


def test_union_is_n_root_over_three_members(tmp_path):
    union = UnionSource(
        [
            make_source(tmp_path, "one", ["a"]),
            make_source(tmp_path, "two", ["b"]),
            make_source(tmp_path, "three", ["c"]),
        ]
    )
    assert sorted(s.name for s in union.list_skills()) == ["a", "b", "c"]


def test_duplicate_skill_error_is_importable_from_package():
    assert agentsquire.DuplicateSkillError is DuplicateSkillError


def test_duplicate_name_across_members_raises_from_list_skills(tmp_path):
    union = UnionSource(
        [
            make_source(tmp_path, "left", ["a", "clash"]),
            make_source(tmp_path, "right", ["clash", "b"]),
        ]
    )
    with pytest.raises(DuplicateSkillError):
        union.list_skills()


def test_duplicate_name_across_members_raises_from_materialize(tmp_path):
    union = UnionSource(
        [
            make_source(tmp_path, "left", ["clash"]),
            make_source(tmp_path, "right", ["clash"]),
        ]
    )
    with pytest.raises(DuplicateSkillError):
        with union.materialize("clash"):
            pass


def test_duplicate_error_message_names_the_skill_and_both_roots(tmp_path):
    left = make_source(tmp_path, "left", ["clash"])
    right = make_source(tmp_path, "right", ["clash"])
    union = UnionSource([left, right])
    with pytest.raises(DuplicateSkillError) as excinfo:
        union.list_skills()
    message = str(excinfo.value)
    assert "clash" in message
    assert str(left.root) in message
    assert str(right.root) in message
