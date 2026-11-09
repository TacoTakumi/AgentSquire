"""The single network step of the release check.

fetch is the only function in the package that opens a URL. It sends a
User-Agent that names agentsquire and its version, uses a 3 second socket
timeout, and stops reading at a fixed size limit. Every test here replaces
the opener seam, and a guard fixture fails any test that creates a socket.
"""

import socket
import urllib.error
from pathlib import Path

import pytest

import agentsquire
from agentsquire import _pypi

URL = "https://pypi.org/pypi/agentsquire/json"
SRC = Path(__file__).parent.parent / "src" / "agentsquire"


class FakeResponse:
    """A response body with the read / close / context manager surface."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.read_sizes: list[int | None] = []
        self.closed = False

    def read(self, amount: int | None = None) -> bytes:
        self.read_sizes.append(amount)
        if amount is None or amount < 0:
            return self.body
        return self.body[:amount]

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class FakeOpener:
    """Records each request and timeout, then returns the given response."""

    def __init__(self, response: FakeResponse | None = None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[object, object]] = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def no_socket(monkeypatch):
    """Fail the test if anything tries to create a real socket."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a real socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def patch_opener(monkeypatch, body: bytes = b"{}", error=None) -> FakeOpener:
    opener = FakeOpener(FakeResponse(body), error)
    monkeypatch.setattr(_pypi, "_open", opener)
    return opener


def test_module_constants():
    assert _pypi.SOCKET_TIMEOUT == 3.0
    assert _pypi.MAX_BYTES == 4 * 1024 * 1024


def test_fetch_returns_the_body(monkeypatch):
    body = b'{"info": {"version": "1.2.3"}}'
    opener = patch_opener(monkeypatch, body)

    assert _pypi.fetch(URL) == body
    assert len(opener.calls) == 1


def test_fetch_requests_the_given_url(monkeypatch):
    opener = patch_opener(monkeypatch)

    _pypi.fetch(URL)

    request, _ = opener.calls[0]
    assert request.full_url == URL
    assert request.get_method() == "GET"


def test_user_agent_names_agentsquire_and_its_version(monkeypatch):
    opener = patch_opener(monkeypatch)

    _pypi.fetch(URL)

    request, _ = opener.calls[0]
    user_agent = request.get_header("User-agent")
    assert user_agent.startswith(f"agentsquire/{agentsquire.__version__}")


def test_request_accepts_json_and_does_not_ask_for_gzip(monkeypatch):
    opener = patch_opener(monkeypatch)

    _pypi.fetch(URL)

    request, _ = opener.calls[0]
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Accept-encoding") is None


def test_socket_timeout_is_three_seconds(monkeypatch):
    opener = patch_opener(monkeypatch)

    _pypi.fetch(URL)

    _, timeout = opener.calls[0]
    assert timeout == 3


def test_response_is_closed(monkeypatch):
    opener = patch_opener(monkeypatch)

    _pypi.fetch(URL)

    assert opener.response.closed


def test_body_at_the_size_limit_is_returned(monkeypatch):
    monkeypatch.setattr(_pypi, "MAX_BYTES", 16)
    body = b"x" * 16
    patch_opener(monkeypatch, body)

    assert _pypi.fetch(URL) == body


def test_body_over_the_size_limit_raises_value_error(monkeypatch):
    monkeypatch.setattr(_pypi, "MAX_BYTES", 16)
    opener = patch_opener(monkeypatch, b"x" * 17)

    with pytest.raises(ValueError):
        _pypi.fetch(URL)
    assert opener.response.closed


def test_read_stops_one_byte_past_the_size_limit(monkeypatch):
    monkeypatch.setattr(_pypi, "MAX_BYTES", 16)
    opener = patch_opener(monkeypatch, b"x" * 1000)

    with pytest.raises(ValueError):
        _pypi.fetch(URL)
    assert opener.response.read_sizes == [17]


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/pypi/agentsquire/json",
        "file:///etc/hostname",
        "ftp://pypi.org/pypi/agentsquire/json",
        "pypi.org/pypi/agentsquire/json",
        "",
    ],
)
def test_non_https_url_raises_value_error_and_opens_nothing(monkeypatch, url):
    opener = patch_opener(monkeypatch)

    with pytest.raises(ValueError):
        _pypi.fetch(url)
    assert opener.calls == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no route to host"),
        urllib.error.HTTPError(URL, 404, "Not Found", None, None),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
    ],
)
def test_os_error_from_the_opener_propagates(monkeypatch, error):
    patch_opener(monkeypatch, error=error)

    with pytest.raises(OSError) as raised:
        _pypi.fetch(URL)
    assert raised.value is error


def test_pypi_module_is_the_only_one_that_opens_a_url():
    offenders = [
        path.name
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "_pypi.py" and "urlopen" in path.read_text()
    ]
    assert offenders == []
