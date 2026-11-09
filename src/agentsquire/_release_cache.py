"""Per-distribution cache of the newest released version.

One small JSON file per normalized distribution name, in the directory
``agentsquire`` under the user cache root: ``XDG_CACHE_HOME`` (or
``~/.cache`` when that is unset or empty) on POSIX, ``LOCALAPPDATA`` on
Windows. The file holds the newest version and the time of the check, and
nothing else. A write goes to a temp file in the same directory and is then
moved into place, so a reader never sees a partial file. The cache is an
optimisation only: a failed read means "no cache", a failed write is
ignored, and neither function raises.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Directory below the user cache root that holds every cache file.
CACHE_DIR_NAME = "agentsquire"

_SEPARATOR_RUN = re.compile(r"[-_.]+")


def _is_windows() -> bool:
    """True on Windows. A separate function so that a test can patch it."""
    return sys.platform == "win32"


def normalize_name(name: str) -> str:
    """Lower-case the name and turn each run of '-', '_' and '.' into one '-'."""
    return _SEPARATOR_RUN.sub("-", name).lower()


def _cache_root() -> Path:
    """The user cache root for this platform."""
    if _is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local)
        return Path.home() / "AppData" / "Local"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".cache"


def cache_path(distribution: str) -> Path:
    """The cache file for a distribution. Every spelling gives the same file."""
    return _cache_root() / CACHE_DIR_NAME / f"{normalize_name(distribution)}.json"


def read_cache(distribution: str) -> str | None:
    """Return the cached newest version, or None when there is no usable cache.

    A missing file, an unreadable file, invalid JSON and JSON of the wrong
    shape all mean "no cache". Never raises.
    """
    try:
        text = cache_path(distribution).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError, RuntimeError):
        # ValueError covers invalid JSON and invalid UTF-8. RuntimeError is
        # what Path.home() raises when the home directory cannot be found.
        return None
    if not isinstance(data, dict):
        return None
    newest = data.get("newest")
    if not isinstance(newest, str) or not newest:
        return None
    return newest


def write_cache(distribution: str, newest: str) -> None:
    """Record the newest version and the check time. Never raises.

    The content goes to a temp file in the cache directory, which is then
    moved over the cache file. On a failure the temp file is removed and the
    previous cache file, if any, stays as it was.
    """
    try:
        path = cache_path(distribution)
        payload = json.dumps(
            {
                "newest": newest,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp creates the file with mode 0600 on POSIX.
        fd, temp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            if not _is_windows():
                os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    except (OSError, ValueError, RuntimeError):
        return
