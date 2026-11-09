"""Release result types and the release-number comparison.

compare_versions looks at the release numbers only: trailing zeros are
padded, text after the release numbers is ignored, an optional leading 'v'
is accepted, and a string with no leading release number (or with an epoch)
gives the status unknown instead of an error.
"""

import dataclasses
import enum
import re
from pathlib import Path

import pytest

import agentsquire
import agentsquire.verbs
from agentsquire import ReleaseCheck, ReleaseStatus
from agentsquire.release import compare_versions

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


@pytest.mark.parametrize(
    ("installed", "newest", "expected"),
    [
        ("1.2.0", "1.3.0", ReleaseStatus.UPDATE_AVAILABLE),
        ("1.9", "1.10", ReleaseStatus.UPDATE_AVAILABLE),
        ("1.0", "1.0.0", ReleaseStatus.UP_TO_DATE),
        ("1.3.0.dev1", "1.3.0", ReleaseStatus.UP_TO_DATE),
        ("1.3.0.post1", "1.3.0", ReleaseStatus.UP_TO_DATE),
        ("2.0.0", "1.9.9", ReleaseStatus.AHEAD),
        ("v1.2.0", "1.2.0", ReleaseStatus.UP_TO_DATE),
    ],
)
def test_comparison_table(installed, newest, expected):
    assert compare_versions(installed, newest) is expected


@pytest.mark.parametrize(
    ("installed", "newest", "expected"),
    [
        ("1.2.0", "v1.3.0", ReleaseStatus.UPDATE_AVAILABLE),
        ("1.0.0", "1", ReleaseStatus.UP_TO_DATE),
        ("1.0.1", "1", ReleaseStatus.AHEAD),
        ("1.3.0rc1", "1.3.0", ReleaseStatus.UP_TO_DATE),
        ("1.3.0+local.5", "1.3.0", ReleaseStatus.UP_TO_DATE),
        ("1.3.0", "1.3.0a2", ReleaseStatus.UP_TO_DATE),
        (" 1.2.0\n", "1.2.0", ReleaseStatus.UP_TO_DATE),
        ("0.9.9", "0.10.0", ReleaseStatus.UPDATE_AVAILABLE),
    ],
)
def test_comparison_uses_release_numbers_only(installed, newest, expected):
    assert compare_versions(installed, newest) is expected


@pytest.mark.parametrize("bad", ["unknown", "", "abc", "1!2.0"])
def test_unparseable_version_gives_unknown_in_either_position(bad):
    assert compare_versions(bad, "1.0.0") is ReleaseStatus.UNKNOWN
    assert compare_versions("1.0.0", bad) is ReleaseStatus.UNKNOWN


@pytest.mark.parametrize("bad", ["v", ".1.0", "v1!2.0", "-1.0"])
def test_more_unparseable_versions_give_unknown(bad):
    assert compare_versions(bad, "1.0.0") is ReleaseStatus.UNKNOWN
    assert compare_versions("1.0.0", bad) is ReleaseStatus.UNKNOWN


def test_none_gives_unknown():
    assert compare_versions(None, "1.0.0") is ReleaseStatus.UNKNOWN
    assert compare_versions("1.0.0", None) is ReleaseStatus.UNKNOWN
    assert compare_versions(None, None) is ReleaseStatus.UNKNOWN


def test_comparison_never_gives_check_failed():
    pairs = [
        ("1.0", "2.0"),
        ("2.0", "1.0"),
        ("1.0", "1.0"),
        (None, "1.0"),
        ("abc", "1.0"),
    ]
    results = {compare_versions(installed, newest) for installed, newest in pairs}
    assert ReleaseStatus.CHECK_FAILED not in results


def test_release_status_values():
    assert issubclass(ReleaseStatus, enum.Enum)
    assert [member.value for member in ReleaseStatus] == [
        "up-to-date",
        "update-available",
        "ahead",
        "unknown",
        "check-failed",
    ]


def test_release_check_fields():
    assert dataclasses.is_dataclass(ReleaseCheck)
    assert [field.name for field in dataclasses.fields(ReleaseCheck)] == [
        "distribution",
        "installed",
        "newest",
        "status",
        "upgrade_command",
        "error",
    ]


def test_release_check_is_frozen():
    check = ReleaseCheck(
        distribution="example",
        installed="1.2.0",
        newest="1.3.0",
        status=ReleaseStatus.UPDATE_AVAILABLE,
        upgrade_command="pip install --upgrade example",
        error=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.newest = "9.9.9"
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.status = ReleaseStatus.UP_TO_DATE
    assert check.newest == "1.3.0"


def test_types_are_exported_from_the_package():
    assert agentsquire.ReleaseCheck is ReleaseCheck
    assert agentsquire.ReleaseStatus is ReleaseStatus
    assert "ReleaseCheck" in agentsquire.__all__
    assert "ReleaseStatus" in agentsquire.__all__


def test_update_result_keeps_its_meaning():
    assert agentsquire.UpdateResult is agentsquire.verbs.UpdateResult


def test_no_new_dependency():
    text = PYPROJECT.read_text()
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    assert block is not None
    names = {
        re.match(r"[A-Za-z0-9_.-]+", entry).group(0).lower()
        for entry in re.findall(r'"([^"]+)"', block.group(1))
    }
    assert names <= {"pyyaml", "click", "questionary"}
