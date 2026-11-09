import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentsquire import _release_cache
from agentsquire._release_cache import (
    cache_path,
    normalize_name,
    read_cache,
    write_cache,
)


@pytest.fixture
def cache_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cache at a temp directory, never at the real one."""
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(_release_cache, "_is_windows", lambda: False)
    return xdg


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("agent-wiki-kb", "agent-wiki-kb"),
        ("Agent_Wiki.KB", "agent-wiki-kb"),
        ("AGENTSQUIRE", "agentsquire"),
        ("a__b..c--d", "a-b-c-d"),
        ("a-_.b", "a-b"),
    ],
)
def test_normalize_name(name: str, expected: str) -> None:
    assert normalize_name(name) == expected


def test_cache_path_under_xdg_cache_home(cache_home: Path) -> None:
    assert cache_path("Agent_Wiki.KB") == cache_home / "agentsquire" / "agent-wiki-kb.json"


def test_cache_path_falls_back_to_home_cache_when_unset(
    cache_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME")
    expected = tmp_path / "home" / ".cache" / "agentsquire" / "demo.json"
    assert cache_path("demo") == expected


def test_cache_path_falls_back_to_home_cache_when_empty(
    cache_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    expected = tmp_path / "home" / ".cache" / "agentsquire" / "demo.json"
    assert cache_path("demo") == expected


def test_cache_path_on_windows_uses_localappdata(
    cache_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(_release_cache, "_is_windows", lambda: True)
    assert cache_path("Agent_Wiki.KB") == local / "agentsquire" / "agent-wiki-kb.json"


def test_write_on_windows_lands_under_localappdata(
    cache_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(_release_cache, "_is_windows", lambda: True)
    write_cache("demo", "1.2.3")
    assert (local / "agentsquire" / "demo.json").is_file()
    assert not cache_home.exists()
    assert read_cache("demo") == "1.2.3"


def test_is_windows_follows_sys_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert _release_cache._is_windows() is True
    monkeypatch.setattr(sys, "platform", "linux")
    assert _release_cache._is_windows() is False


def test_write_then_read_round_trip(cache_home: Path) -> None:
    write_cache("demo", "1.2.3")
    assert read_cache("demo") == "1.2.3"


def test_two_spellings_share_one_file(cache_home: Path) -> None:
    write_cache("Agent_Wiki.KB", "1.0.0")
    write_cache("agent-wiki-kb", "1.1.0")
    directory = cache_home / "agentsquire"
    assert [p.name for p in directory.iterdir()] == ["agent-wiki-kb.json"]
    assert read_cache("Agent_Wiki.KB") == "1.1.0"
    assert read_cache("agent-wiki-kb") == "1.1.0"


def test_write_under_home_cache_when_xdg_unset(
    cache_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME")
    write_cache("demo", "1.2.3")
    assert (tmp_path / "home" / ".cache" / "agentsquire" / "demo.json").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_file_mode_is_0600(cache_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = os.umask(0)
    try:
        write_cache("demo", "1.2.3")
    finally:
        os.umask(old)
    assert stat.S_IMODE(cache_path("demo").stat().st_mode) == 0o600


def test_file_holds_newest_and_check_time_only(cache_home: Path) -> None:
    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    write_cache("demo", "1.2.3")
    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    data = json.loads(cache_path("demo").read_text(encoding="utf-8"))
    assert set(data) == {"newest", "checked_at"}
    assert data["newest"] == "1.2.3"
    checked_at = datetime.fromisoformat(data["checked_at"])
    assert checked_at.utcoffset() == timedelta(0)
    assert before <= checked_at <= after


def test_no_temp_file_left_after_write(cache_home: Path) -> None:
    write_cache("demo", "1.2.3")
    write_cache("demo", "1.2.4")
    assert [p.name for p in (cache_home / "agentsquire").iterdir()] == ["demo.json"]


def test_write_swallows_replace_failure_and_removes_temp_file(
    cache_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only directory")

    monkeypatch.setattr(_release_cache.os, "replace", refuse)
    write_cache("demo", "1.2.3")
    assert list((cache_home / "agentsquire").iterdir()) == []
    assert read_cache("demo") is None


def test_write_swallows_unwritable_directory(
    cache_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError("directory not writable")

    monkeypatch.setattr(_release_cache.tempfile, "mkstemp", refuse)
    write_cache("demo", "1.2.3")
    assert read_cache("demo") is None


def test_write_swallows_directory_creation_failure(
    cache_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A regular file where the cache root should be: mkdir fails for real.
    cache_home.write_text("not a directory")
    write_cache("demo", "1.2.3")
    assert cache_home.read_text() == "not a directory"
    assert read_cache("demo") is None


def test_failed_write_keeps_the_previous_file(
    cache_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache("demo", "1.2.3")

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_release_cache.os, "replace", refuse)
    write_cache("demo", "9.9.9")
    assert read_cache("demo") == "1.2.3"
    assert [p.name for p in (cache_home / "agentsquire").iterdir()] == ["demo.json"]


def test_read_missing_file_gives_none(cache_home: Path) -> None:
    assert read_cache("demo") is None
    # A read never creates the cache directory.
    assert not cache_home.exists()


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{not json",
        "[]",
        '"1.2.3"',
        "null",
        "{}",
        '{"checked_at": "2026-01-01T00:00:00+00:00"}',
        '{"newest": 3}',
        '{"newest": null}',
        '{"newest": ""}',
        '{"newest": ["1.2.3"]}',
    ],
)
def test_read_malformed_file_gives_none(cache_home: Path, content: str) -> None:
    path = cache_path("demo")
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert read_cache("demo") is None


def test_read_invalid_bytes_gives_none(cache_home: Path) -> None:
    path = cache_path("demo")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00{")
    assert read_cache("demo") is None


def test_read_oserror_gives_none(cache_home: Path) -> None:
    # A directory where the file should be: the read fails with an OSError.
    cache_path("demo").mkdir(parents=True)
    assert read_cache("demo") is None
