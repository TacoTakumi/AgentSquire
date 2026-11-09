"""UnionSource: disjoint N-root merge over the SkillSource seam.

A UnionSource composes any number of member sources into one, listing the union
of their skills (each carrying its owning source's content hash) and delegating
materialize() to the member that owns a given name. Roots are disjoint by
construction; a name in two roots is a packaging mistake handled separately.
"""

import os
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


def test_duplicate_name_in_two_of_three_members_raises(tmp_path):
    one = make_source(tmp_path, "one", ["a", "clash"])
    two = make_source(tmp_path, "two", ["b"])
    three = make_source(tmp_path, "three", ["clash", "c"])
    union = UnionSource([one, two, three])

    with pytest.raises(DuplicateSkillError) as excinfo:
        union.list_skills()
    message = str(excinfo.value)
    assert "clash" in message
    assert str(one.root) in message
    assert str(three.root) in message
    assert str(two.root) not in message

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


class CountingSource:
    """Wraps a source and counts how often it is enumerated."""

    def __init__(self, inner):
        self.inner = inner
        self.root = inner.root
        self.list_calls = 0

    def list_skills(self):
        self.list_calls += 1
        return self.inner.list_skills()

    def materialize(self, name):
        return self.inner.materialize(name)


def test_materialize_does_not_enumerate_any_member(tmp_path):
    left = CountingSource(make_source(tmp_path, "left", ["a", "b"]))
    right = CountingSource(make_source(tmp_path, "right", ["c", "d"]))
    union = UnionSource([left, right])

    with union.materialize("c") as path:
        assert path == right.inner.root / "c"

    assert left.list_calls == 0
    assert right.list_calls == 0


def test_materialize_does_not_hash_any_skill(tmp_path, monkeypatch):
    union = UnionSource(
        [make_source(tmp_path, "left", ["a", "b"]), make_source(tmp_path, "right", ["c"])]
    )

    def fail(path):
        raise AssertionError(f"hashed {path}")

    monkeypatch.setattr("agentsquire.sources.skill_content_hash", fail)
    with union.materialize("a") as path:
        assert path.name == "a"


def test_materialize_duplicate_error_names_the_skill_and_both_roots(tmp_path):
    left = make_source(tmp_path, "left", ["clash", "a"])
    right = make_source(tmp_path, "right", ["b", "clash"])
    union = UnionSource([left, right])
    with pytest.raises(DuplicateSkillError) as excinfo:
        with union.materialize("clash"):
            pass
    message = str(excinfo.value)
    assert "clash" in message
    assert str(left.root) in message
    assert str(right.root) in message


def test_keyerror_raised_inside_the_with_body_propagates(tmp_path):
    union = UnionSource(
        [make_source(tmp_path, "left", ["a"]), make_source(tmp_path, "right", ["b"])]
    )
    with pytest.raises(KeyError, match="from-body"):
        with union.materialize("a"):
            raise KeyError("from-body")


NON_PLAIN_NAMES = ["", ".", "..", "../outside", "sub/a"]


@pytest.mark.parametrize("name", NON_PLAIN_NAMES)
def test_materialize_non_plain_name_raises_keyerror_two_members(tmp_path, name):
    # A name that is not one plain path component is never a skill. With two
    # directory members it must not look like a duplicate either.
    (tmp_path / "outside").mkdir()
    one = make_source(tmp_path, "one", ["a"])
    two = make_source(tmp_path, "two", ["b"])
    (one.root / "sub" / "a").mkdir(parents=True)
    union = UnionSource([one, two])
    with pytest.raises(KeyError):
        with union.materialize(name):
            pass


@pytest.mark.parametrize("name", NON_PLAIN_NAMES)
def test_materialize_non_plain_name_raises_keyerror_one_member(tmp_path, name):
    # With one directory member the root itself, or a directory outside it,
    # must never be yielded as a skill.
    (tmp_path / "outside").mkdir()
    one = make_source(tmp_path, "one", ["a"])
    (one.root / "sub" / "a").mkdir(parents=True)
    union = UnionSource([one])
    with pytest.raises(KeyError):
        with union.materialize(name):
            pass


posix_only = pytest.mark.skipif(os.sep != "/", reason="a backslash is a separator here")


@posix_only
def test_materialize_yields_a_listed_name_that_holds_a_backslash(tmp_path):
    # Where a backslash is an ordinary file-name character, a listed name
    # that holds one must still materialize.
    one = make_source(tmp_path, "one", ["a", "we\\ird"])
    union = UnionSource([one])
    assert "we\\ird" in [skill.name for skill in union.list_skills()]
    with union.materialize("we\\ird") as path:
        assert path == one.root / "we\\ird"


@posix_only
def test_install_over_a_union_survives_a_name_that_holds_a_backslash(tmp_path):
    # Every listed name reaches materialize during an install; one odd name
    # must not stop the run for the others.
    from agentsquire.harnesses import CLAUDE_CODE
    from agentsquire.verbs import install

    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    one = make_source(tmp_path, "one", ["a", "we\\ird"])
    install(
        UnionSource([one]),
        CLAUDE_CODE,
        scope="user",
        home=home,
        project=project,
        source_package="fixture-consumer",
        source_version="1.2.3",
    )
    assert list(home.rglob("a/SKILL.md"))
