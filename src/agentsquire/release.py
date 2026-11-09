"""Release check result types and the release-number comparison.

A release check compares the installed version of a distribution with the
newest published one. The comparison looks at the release numbers only
(the dotted integers at the start of a version string), so it needs no
version-parsing dependency. Missing trailing numbers count as zero, text
after the release numbers (pre, post, dev and local parts) is ignored, and
an optional leading 'v' is accepted. A string with no leading release
number, or with an epoch, does not parse; the result is then unknown, never
an error.

check_for_update asks PyPI for the newest version. It makes one request,
returns within TOTAL_TIMEOUT seconds and never raises: each failure becomes
a result with the status check-failed and a one-line reason.
"""

from __future__ import annotations

import enum
import json
import re
import ssl
import threading
import urllib.error
import urllib.parse
from dataclasses import dataclass
from itertools import zip_longest

from agentsquire import _install, _release_cache

# Seconds allowed for one check_for_update call, from start to result. The
# value is read at call time.
TOTAL_TIMEOUT = 5.0

# The longest reason that a failed check reports.
_MAX_REASON = 200

# The release numbers at the start of a version string, after an optional
# 'v'. The match is the longest run of dotted integers.
_RELEASE = re.compile(r"[vV]?([0-9]+(?:\.[0-9]+)*)")


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
    text = version.strip()
    match = _RELEASE.match(text)
    if match is None:
        return None
    # A '!' after the numbers marks them as an epoch ('1!2.0'), not as
    # release numbers.
    if text.startswith("!", match.end()):
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


class _CheckFailed(Exception):
    """The check cannot give a newest version. The message is the reason."""


def _one_line(text: object) -> str:
    """Collapse the text to one line of limited length."""
    line = " ".join(str(text).split())
    if len(line) > _MAX_REASON:
        line = line[: _MAX_REASON - 3] + "..."
    return line


def _failure_reason(exc: BaseException) -> str:
    """A short, readable, one-line reason for a failed check. Never empty."""
    if isinstance(exc, _CheckFailed):
        return _one_line(exc) or "check failed"
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "not found on PyPI"
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        # urllib wraps the socket or TLS error; the wrapped one is the reason.
        exc = exc.reason
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "certificate verification failed"
    if isinstance(exc, TimeoutError):
        return "timed out"
    if isinstance(exc, urllib.error.URLError):
        text = _one_line(exc.reason)
    elif isinstance(exc, OSError) and exc.strerror:
        text = _one_line(exc.strerror)
    else:
        text = _one_line(exc)
    return text or type(exc).__name__


def _fetch_body(url: str) -> object:
    """Fetch the URL in a daemon thread and wait at most TOTAL_TIMEOUT.

    Returns what the fetch returned, raises what it raised, and raises
    _CheckFailed('timed out') when the fetch is not done in time. The thread
    is a daemon, so a fetch that never returns does not keep the process
    alive.
    """
    # Imported here so that a program that never checks does not load the
    # HTTP client. The attribute is read at call time: a test replaces
    # agentsquire._pypi.fetch.
    from agentsquire import _pypi

    fetch = _pypi.fetch
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["body"] = fetch(url)
        except BaseException as exc:  # reported by the caller's thread
            outcome["error"] = exc

    thread = threading.Thread(target=run, name="agentsquire-release-check", daemon=True)
    thread.start()
    thread.join(TOTAL_TIMEOUT)
    if thread.is_alive():
        raise _CheckFailed("timed out")
    error = outcome.get("error")
    if isinstance(error, Exception):
        raise error
    if isinstance(error, BaseException):
        # An exit or interrupt request that was raised in the fetch thread
        # is a failed fetch, not a request to this thread.
        raise _CheckFailed(type(error).__name__)
    return outcome.get("body")


def _newest_version(body: object) -> str:
    """Read info.version from a PyPI JSON document, or raise _CheckFailed."""
    try:
        if not isinstance(body, (bytes, bytearray)):
            raise ValueError("the body is not bytes")
        document = json.loads(bytes(body).decode("utf-8"))
        newest = document["info"]["version"]
    except (ValueError, KeyError, TypeError, RecursionError):
        raise _CheckFailed("unexpected response from PyPI") from None
    if not isinstance(newest, str) or not newest.strip():
        raise _CheckFailed("unexpected response from PyPI")
    return newest


def check_for_update(distribution: str, version: str | None = None) -> ReleaseCheck:
    """Ask PyPI for the newest version of the distribution.

    installed is the version argument when one is passed, else the version
    from the install metadata, else None. The check makes one HTTPS GET of
    the PyPI JSON document of the distribution and returns within
    TOTAL_TIMEOUT seconds. A successful check records the newest version in
    the cache file of the distribution, and upgrade_command is set only when
    the status is update-available. A failed check has the status
    check-failed, a one-line reason in error and newest None, and writes
    nothing. Never raises. The environment does not turn this check off:
    the caller asked for it.
    """
    installed = None
    try:
        if version is not None:
            installed = version
        else:
            try:
                installed = _install.installed_version(distribution)
            except Exception:
                installed = None
        url = "https://pypi.org/pypi/{}/json".format(
            urllib.parse.quote(distribution, safe="")
        )
        newest = _newest_version(_fetch_body(url))
        try:
            _release_cache.write_cache(distribution, newest)
        except Exception:
            pass
        status = compare_versions(installed, newest)
        command = None
        if status is ReleaseStatus.UPDATE_AVAILABLE:
            try:
                command = _install.upgrade_command(distribution)
            except Exception:
                command = None
        return ReleaseCheck(
            distribution=distribution,
            installed=installed,
            newest=newest,
            status=status,
            upgrade_command=command,
        )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        try:
            reason = _failure_reason(exc)
        except Exception:
            reason = "check failed"
        return ReleaseCheck(
            distribution=distribution,
            installed=installed,
            newest=None,
            status=ReleaseStatus.CHECK_FAILED,
            error=reason,
        )
