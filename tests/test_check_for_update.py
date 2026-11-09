"""check_for_update: one fetch, a total time limit, and a result that never raises.

Every test replaces ``agentsquire._pypi.fetch``; no test opens a connection.
The cache root is a temp directory for every test.
"""

import email.message
import importlib.metadata
import json
import os
import ssl
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
from pathlib import Path

import pytest

import agentsquire
from agentsquire import _install, _pypi, _release_cache, release
from agentsquire.release import ReleaseCheck, ReleaseStatus, check_for_update

# A distribution name that is not installed in any test environment.
ABSENT = "agentsquire-test-absent-distribution"


def pypi_body(version="2.0.0"):
    """A PyPI JSON document, as bytes, with the given info.version."""
    return json.dumps({"info": {"name": "x", "version": version}, "releases": {}}).encode()


def http_error(code):
    return urllib.error.HTTPError(
        "https://pypi.org/pypi/x/json", code, "reason text", email.message.Message(), None
    )


class FetchStub:
    """Replacement for _pypi.fetch that records each call."""

    def __init__(self, result=None, error=None):
        self.result = pypi_body() if result is None and error is None else result
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def cache_home(tmp_path, monkeypatch):
    """Point the cache root at a temp directory."""
    home = tmp_path / "cache-home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(home))
    monkeypatch.setattr(_release_cache, "_is_windows", lambda: False)
    return home


@pytest.fixture
def stub_fetch(monkeypatch):
    """Install a FetchStub and return the function that builds it."""

    def install(result=None, error=None):
        stub = FetchStub(result=result, error=error)
        monkeypatch.setattr(_pypi, "fetch", stub)
        return stub

    return install


@pytest.fixture
def uv_tool_env(tmp_path, monkeypatch):
    """Make the running environment look like a uv tool environment."""
    prefix = tmp_path / "uv-tool-env"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(_install, "_is_editable", lambda distribution: False)
    return prefix


# --- the fetch and the newest version -------------------------------------


def test_total_timeout_default():
    assert release.TOTAL_TIMEOUT == 5.0


def test_import_paths_work_in_a_fresh_process():
    for statement in (
        "import agentsquire",
        "from agentsquire.release import check_for_update",
        "import agentsquire.release",
    ):
        done = subprocess.run(
            [sys.executable, "-c", statement], capture_output=True, text=True, timeout=60
        )
        assert done.returncode == 0, done.stderr


def test_returns_newest_version_from_one_fetch(stub_fetch):
    stub = stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.0.0")
    assert isinstance(result, ReleaseCheck)
    assert result.distribution == "x"
    assert result.newest == "2.0.0"
    assert result.installed == "1.0.0"
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert result.error is None
    assert stub.urls == ["https://pypi.org/pypi/x/json"]


def test_url_uses_the_distribution_name(stub_fetch):
    stub = stub_fetch()
    check_for_update("agent-wiki", "1.0.0")
    assert stub.urls == ["https://pypi.org/pypi/agent-wiki/json"]


def test_url_quotes_the_distribution_name(stub_fetch):
    stub = stub_fetch()
    check_for_update("a b/c?d", "1.0.0")
    assert stub.urls == ["https://pypi.org/pypi/a%20b%2Fc%3Fd/json"]


def test_fetch_is_looked_up_at_call_time(monkeypatch):
    first = FetchStub(pypi_body("2.0.0"))
    second = FetchStub(pypi_body("3.0.0"))
    monkeypatch.setattr(_pypi, "fetch", first)
    assert check_for_update("x", "1.0.0").newest == "2.0.0"
    monkeypatch.setattr(_pypi, "fetch", second)
    assert check_for_update("x", "1.0.0").newest == "3.0.0"
    assert len(first.urls) == 1
    assert len(second.urls) == 1


@pytest.mark.parametrize(
    "installed, newest, status",
    [
        ("1.0.0", "2.0.0", ReleaseStatus.UPDATE_AVAILABLE),
        ("2.0.0", "2.0.0", ReleaseStatus.UP_TO_DATE),
        ("3.0.0", "2.0.0", ReleaseStatus.AHEAD),
        ("not a version", "2.0.0", ReleaseStatus.UNKNOWN),
    ],
)
def test_status_comes_from_the_comparison(stub_fetch, installed, newest, status):
    stub_fetch(pypi_body(newest))
    result = check_for_update("x", installed)
    assert result.status is status
    assert result.installed == installed
    assert result.newest == newest
    assert result.error is None


@pytest.mark.parametrize("name", ["CI", "AGENTSQUIRE_NO_UPDATE_CHECK"])
def test_environment_switches_do_not_disable_the_check(stub_fetch, monkeypatch, name):
    monkeypatch.setenv(name, "1")
    stub = stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert len(stub.urls) == 1


# --- the total time limit -------------------------------------------------


def test_blocking_fetch_times_out(monkeypatch, cache_home):
    release_fetch = threading.Event()
    started = threading.Event()

    def blocking(url):
        started.set()
        release_fetch.wait(30)
        return pypi_body()

    monkeypatch.setattr(_pypi, "fetch", blocking)
    monkeypatch.setattr(release, "TOTAL_TIMEOUT", 0.2)
    try:
        begin = time.monotonic()
        result = check_for_update("x", "1.0.0")
        elapsed = time.monotonic() - begin
        assert started.is_set()
        assert elapsed < 1.2
        assert result.status is ReleaseStatus.CHECK_FAILED
        assert result.error == "timed out"
        assert result.newest is None
        assert result.installed == "1.0.0"
        assert result.upgrade_command is None
        assert not _release_cache.cache_path("x").exists()
    finally:
        release_fetch.set()


def test_fetch_runs_in_a_daemon_thread(monkeypatch):
    seen = {}

    def fetch(url):
        seen["daemon"] = threading.current_thread().daemon
        seen["main"] = threading.current_thread() is threading.main_thread()
        return pypi_body()

    monkeypatch.setattr(_pypi, "fetch", fetch)
    check_for_update("x", "1.0.0")
    assert seen == {"daemon": True, "main": False}


def test_process_exits_while_the_fetch_still_blocks(tmp_path):
    script = textwrap.dedent(
        """
        import threading

        from agentsquire import _pypi, release

        never = threading.Event()


        def blocking(url):
            never.wait()
            return b""


        _pypi.fetch = blocking
        release.TOTAL_TIMEOUT = 0.2
        result = release.check_for_update("x", "1.0.0")
        print(result.status.value, "|", result.error)
        """
    )
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path / "sub-cache"))
    begin = time.monotonic()
    # The fetch in the child never returns: the child can exit only if the
    # fetch thread is a daemon. The timeout here turns a hang into a failure.
    done = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    elapsed = time.monotonic() - begin
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "check-failed | timed out"
    assert elapsed < 20


# --- failures -------------------------------------------------------------


FAILURES = [
    pytest.param({"error": urllib.error.URLError("Name or service not known")}, id="url-error"),
    pytest.param(
        {"error": urllib.error.URLError(OSError(101, "Network is unreachable"))},
        id="url-error-oserror-reason",
    ),
    pytest.param(
        {"error": ssl.SSLCertVerificationError(1, "certificate verify failed\nself-signed")},
        id="tls-certificate",
    ),
    pytest.param(
        {"error": urllib.error.URLError(ssl.SSLCertVerificationError(1, "verify failed"))},
        id="tls-certificate-in-url-error",
    ),
    pytest.param({"error": TimeoutError("timed out")}, id="timeout"),
    pytest.param({"error": TimeoutError()}, id="timeout-no-message"),
    pytest.param({"error": urllib.error.URLError(TimeoutError())}, id="timeout-in-url-error"),
    pytest.param({"error": http_error(404)}, id="http-404"),
    pytest.param({"error": http_error(500)}, id="http-500"),
    pytest.param({"error": OSError()}, id="oserror-no-message"),
    pytest.param({"error": ValueError("response body is larger\nthan the limit")}, id="value-error"),
    pytest.param({"error": RuntimeError("multi\nline\r\nmessage")}, id="other-error"),
    pytest.param({"result": b"<html>not json</html>"}, id="invalid-json"),
    pytest.param({"result": b"\xff\xfe\x00"}, id="invalid-utf8"),
    pytest.param({"result": b""}, id="empty-body"),
    pytest.param({"result": "a str, not bytes"}, id="body-not-bytes"),
    pytest.param({"result": b"[1, 2, 3]"}, id="json-not-an-object"),
    pytest.param({"result": b'{"releases": {}}'}, id="json-without-info"),
    pytest.param({"result": b'{"info": "text"}'}, id="info-not-an-object"),
    pytest.param({"result": b'{"info": {"name": "x"}}'}, id="json-without-version"),
    pytest.param({"result": b'{"info": {"version": 2}}'}, id="version-not-a-string"),
    pytest.param({"result": b'{"info": {"version": null}}'}, id="version-null"),
    pytest.param({"result": b'{"info": {"version": ""}}'}, id="version-empty"),
]


@pytest.mark.parametrize("case", FAILURES)
def test_failure_gives_check_failed(stub_fetch, uv_tool_env, case):
    stub = stub_fetch(**case)
    result = check_for_update(ABSENT, "1.0.0")
    assert len(stub.urls) == 1
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert result.newest is None
    assert result.installed == "1.0.0"
    assert result.upgrade_command is None
    assert isinstance(result.error, str)
    assert result.error.strip()
    assert "\n" not in result.error
    assert "\r" not in result.error
    assert result.error.isascii()
    assert not _release_cache.cache_path(ABSENT).exists()


@pytest.mark.parametrize(
    "case, expected",
    [
        ({"error": http_error(404)}, "not found on PyPI"),
        ({"error": http_error(500)}, "HTTP 500"),
        ({"error": urllib.error.URLError("Name or service not known")}, "Name or service not known"),
        (
            {"error": ssl.SSLCertVerificationError(1, "verify failed")},
            "certificate verification failed",
        ),
        (
            {"error": urllib.error.URLError(ssl.SSLCertVerificationError(1, "verify failed"))},
            "certificate verification failed",
        ),
        ({"error": TimeoutError()}, "timed out"),
        ({"error": urllib.error.URLError(TimeoutError())}, "timed out"),
        ({"result": b"not json"}, "unexpected response from PyPI"),
        ({"result": b'{"info": {"version": 2}}'}, "unexpected response from PyPI"),
    ],
)
def test_failure_reason_is_short_and_readable(stub_fetch, case, expected):
    stub_fetch(**case)
    assert check_for_update("x", "1.0.0").error == expected


def test_never_raises_when_a_building_block_fails(stub_fetch, monkeypatch):
    stub_fetch(pypi_body("2.0.0"))

    def broken(*args, **kwargs):
        raise RuntimeError("broken\nbuilding block")

    monkeypatch.setattr(release, "compare_versions", broken)
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert result.distribution == "x"
    assert result.installed == "1.0.0"
    assert result.newest is None
    assert result.upgrade_command is None
    assert result.error
    assert "\n" not in result.error


def test_never_raises_when_the_thread_cannot_start(stub_fetch, monkeypatch):
    stub_fetch(pypi_body("2.0.0"))

    def no_thread(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(release.threading, "Thread", no_thread)
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert result.error
    assert "\n" not in result.error


# --- the cache ------------------------------------------------------------


def test_success_writes_newest_and_check_time_only(stub_fetch):
    stub_fetch(pypi_body("2.0.0"))
    check_for_update("My_Dist", "1.0.0")
    path = _release_cache.cache_path("My_Dist")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"newest", "checked_at"}
    assert data["newest"] == "2.0.0"
    assert isinstance(data["checked_at"], str) and data["checked_at"]
    assert _release_cache.read_cache("my-dist") == "2.0.0"


def test_success_replaces_an_earlier_cache(stub_fetch):
    _release_cache.write_cache("x", "1.5.0")
    stub_fetch(pypi_body("2.0.0"))
    check_for_update("x", "1.0.0")
    assert _release_cache.read_cache("x") == "2.0.0"


def test_failure_with_no_earlier_cache_writes_no_file(stub_fetch, cache_home):
    stub_fetch(error=urllib.error.URLError("no network"))
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert not _release_cache.cache_path("x").exists()
    assert not cache_home.exists() or not any(p.is_file() for p in cache_home.rglob("*"))


@pytest.mark.parametrize(
    "case",
    [
        {"error": urllib.error.URLError("no network")},
        {"error": http_error(500)},
        {"result": b"not json"},
        {"result": b'{"info": {}}'},
    ],
)
def test_failure_leaves_an_earlier_cache_unchanged(stub_fetch, case):
    _release_cache.write_cache("x", "1.5.0")
    path = _release_cache.cache_path("x")
    before = path.read_bytes()
    stub_fetch(**case)
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_timeout_leaves_an_earlier_cache_unchanged(monkeypatch):
    _release_cache.write_cache("x", "1.5.0")
    path = _release_cache.cache_path("x")
    before = path.read_bytes()
    release_fetch = threading.Event()
    finished = threading.Event()

    def blocking(url):
        release_fetch.wait(30)
        finished.set()
        return pypi_body("9.9.9")

    monkeypatch.setattr(_pypi, "fetch", blocking)
    monkeypatch.setattr(release, "TOTAL_TIMEOUT", 0.2)
    try:
        result = check_for_update("x", "1.0.0")
        assert result.error == "timed out"
    finally:
        release_fetch.set()
    # A fetch that returns after the limit must not write the cache either.
    assert finished.wait(5)
    time.sleep(0.1)
    assert path.read_bytes() == before


def test_cache_directory_that_cannot_be_written(stub_fetch, tmp_path, monkeypatch):
    # A regular file where the cache root should be: no directory can be
    # made below it, for any user.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert result.newest == "2.0.0"
    assert result.error is None
    assert blocker.read_text(encoding="utf-8") == "x"


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions and a user that is not root",
)
def test_read_only_cache_directory(stub_fetch, cache_home):
    cache_home.mkdir()
    cache_home.chmod(0o500)
    try:
        stub_fetch(pypi_body("1.0.0"))
        result = check_for_update("x", "1.0.0")
        assert result.status is ReleaseStatus.UP_TO_DATE
        assert result.error is None
        assert list(cache_home.iterdir()) == []
    finally:
        cache_home.chmod(0o700)


def test_write_error_from_the_cache_is_ignored(stub_fetch, monkeypatch):
    def broken(distribution, newest):
        raise OSError("disk full")

    monkeypatch.setattr(_release_cache, "write_cache", broken)
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.0.0")
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert result.newest == "2.0.0"
    assert result.error is None


# --- the installed version ------------------------------------------------


def test_version_argument_wins_with_no_metadata_lookup(stub_fetch, monkeypatch):
    lookups = []

    def record(distribution):
        lookups.append(distribution)
        return "9.9.9"

    monkeypatch.setattr(_install, "installed_version", record)
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: lookups.append(name) or "9.9.9"
    )
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.2.3")
    assert result.installed == "1.2.3"
    assert lookups == []


def test_version_argument_wins_for_an_installed_distribution(stub_fetch):
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("agentsquire", "0.0.1")
    assert result.installed == "0.0.1"
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE


def test_no_version_reads_the_install_metadata(stub_fetch):
    expected = importlib.metadata.version("agentsquire")
    stub_fetch(pypi_body(expected))
    result = check_for_update("agentsquire")
    assert result.installed == expected
    assert result.installed == agentsquire.__version__
    assert result.status is ReleaseStatus.UP_TO_DATE


def test_not_installed_and_no_version_is_unknown(stub_fetch):
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update(ABSENT)
    assert result.installed is None
    assert result.newest == "2.0.0"
    assert result.status is ReleaseStatus.UNKNOWN
    assert result.error is None


def test_not_installed_and_no_version_still_reports_a_failure(stub_fetch):
    stub_fetch(error=urllib.error.URLError("no network"))
    result = check_for_update(ABSENT)
    assert result.installed is None
    assert result.status is ReleaseStatus.CHECK_FAILED


def test_metadata_lookup_failure_does_not_raise(stub_fetch, monkeypatch):
    def broken(distribution):
        raise RuntimeError("metadata is broken")

    monkeypatch.setattr(_install, "installed_version", broken)
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x")
    assert isinstance(result, ReleaseCheck)
    assert result.installed is None


# --- the upgrade command --------------------------------------------------


def test_upgrade_command_for_update_available(stub_fetch, uv_tool_env):
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update(ABSENT, "1.0.0")
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert result.upgrade_command == f"uv tool upgrade {ABSENT}"


@pytest.mark.parametrize(
    "version, newest, status",
    [
        ("2.0.0", "2.0.0", ReleaseStatus.UP_TO_DATE),
        ("3.0.0", "2.0.0", ReleaseStatus.AHEAD),
        (None, "2.0.0", ReleaseStatus.UNKNOWN),
        ("no numbers", "2.0.0", ReleaseStatus.UNKNOWN),
    ],
)
def test_no_upgrade_command_for_other_statuses(stub_fetch, uv_tool_env, version, newest, status):
    assert _install.upgrade_command(ABSENT) == f"uv tool upgrade {ABSENT}"
    stub_fetch(pypi_body(newest))
    result = check_for_update(ABSENT, version)
    assert result.status is status
    assert result.upgrade_command is None


def test_no_upgrade_command_for_check_failed(stub_fetch, uv_tool_env):
    assert _install.upgrade_command(ABSENT) == f"uv tool upgrade {ABSENT}"
    stub_fetch(error=http_error(500))
    result = check_for_update(ABSENT, "1.0.0")
    assert result.status is ReleaseStatus.CHECK_FAILED
    assert result.upgrade_command is None


def test_no_upgrade_command_when_the_install_method_is_unknown(stub_fetch, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "plain-env"))
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update(ABSENT, "1.0.0")
    assert result.status is ReleaseStatus.UPDATE_AVAILABLE
    assert result.upgrade_command is None


def test_upgrade_command_lookup_failure_does_not_raise(stub_fetch, monkeypatch):
    def broken(distribution):
        raise RuntimeError("lookup is broken")

    monkeypatch.setattr(_install, "upgrade_command", broken)
    stub_fetch(pypi_body("2.0.0"))
    result = check_for_update("x", "1.0.0")
    assert isinstance(result, ReleaseCheck)
    assert Path(_release_cache.cache_path("x")).exists()
