"""Suite-wide fixtures.

The test suite uses no network. The autouse fixture below makes each socket
connection attempt in the test process fail the test.
"""

import socket

import pytest

BLOCKED_MESSAGE = "network access is blocked in the test suite"


class SocketConnectionBlocked(RuntimeError):
    """A test tried to open a socket connection."""


class SocketGuard:
    """The state of the connection block for one test.

    ``attempts`` holds one line for each blocked call. A test that makes a
    blocked call on purpose clears the list before it ends.
    """

    error = SocketConnectionBlocked

    def __init__(self):
        self.attempts = []


@pytest.fixture(autouse=True)
def block_socket_connections(monkeypatch):
    """Fail the test on a socket connection attempt.

    The connect entry points raise ``SocketConnectionBlocked``. Code under
    test can catch that error, or can make the call in a different thread, so
    the fixture also records each attempt and fails the test at teardown if an
    attempt is left in the record.

    ``socket.socket`` itself stays in place: a test can replace it, and a
    subprocess is not affected.
    """
    guard = SocketGuard()

    def blocked(name):
        def raise_blocked(*args, **kwargs):
            guard.attempts.append(f"{name} args={args[-1:]!r}")
            raise SocketConnectionBlocked(f"{BLOCKED_MESSAGE}: {name} was called")

        return raise_blocked

    monkeypatch.setattr(socket.socket, "connect", blocked("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", blocked("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", blocked("socket.create_connection"))

    yield guard

    if guard.attempts:
        pytest.fail(f"{BLOCKED_MESSAGE}: " + "; ".join(guard.attempts))
