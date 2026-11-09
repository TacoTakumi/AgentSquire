"""Release check result types and the release-number comparison.

A release check compares the installed version of a distribution with the
newest published one. The comparison looks at the release numbers only
(the dotted integers at the start of a version string), so it needs no
version-parsing dependency. Missing trailing numbers count as zero, text
after the release numbers (pre, post, dev and local parts) is ignored, and
an optional leading 'v' is accepted. A string with no leading release
number, or with an epoch, does not parse; the result is then unknown, never
an error.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from itertools import zip_longest

# The release numbers at the start of a version string, after an optional
# 'v'. The lookahead rejects an epoch ('1!2.0'): the number before the '!'
# is not a release number.
_RELEASE = re.compile(r"[vV]?([0-9]+(?:\.[0-9]+)*)(?!!)")


class ReleaseStatus(enum.Enum):
    """How the installed version relates to the newest published one."""

    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    AHEAD = "ahead"
    UNKNOWN = "unknown"
    CHECK_FAILED = "check-failed"


@dataclass(frozen=True)
class ReleaseCheck:
    """The result of one release check for one distribution.

    installed and newest are None when the version is not known.
    upgrade_command is set only when an update is available and a command
    is known. error is set only when the check failed.
    """

    distribution: str
    installed: str | None
    newest: str | None
    status: ReleaseStatus
    upgrade_command: str | None = None
    error: str | None = None


def _release_numbers(version: str | None) -> tuple[int, ...] | None:
    """Return the release numbers of a version string, or None."""
    if not isinstance(version, str):
        return None
    match = _RELEASE.match(version.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(installed: str | None, newest: str | None) -> ReleaseStatus:
    """Compare two version strings by their release numbers.

    Returns update-available when installed is older, up-to-date when the
    release numbers are equal, ahead when installed is newer, and unknown
    when either version is None or does not parse. Never raises and never
    returns check-failed.
    """
    have = _release_numbers(installed)
    want = _release_numbers(newest)
    if have is None or want is None:
        return ReleaseStatus.UNKNOWN
    for mine, theirs in zip_longest(have, want, fillvalue=0):
        if mine < theirs:
            return ReleaseStatus.UPDATE_AVAILABLE
        if mine > theirs:
            return ReleaseStatus.AHEAD
    return ReleaseStatus.UP_TO_DATE
