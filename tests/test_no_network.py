"""The suite-wide fixture blocks each socket connection attempt.

Each test connects to a listener on the loopback address. The listener only
binds and listens, which the fixture permits. A blocked call must raise the
fixture's error and must leave the listener with no pending connection.
"""

import socket

import pytest


@pytest.fixture
def listener():
    """A loopback listener that reports whether a connection arrived."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.setblocking(False)
    yield server
    server.close()


def assert_no_connection(server):
    with pytest.raises(BlockingIOError):
        server.accept()


def test_create_connection_is_blocked(block_socket_connections, listener):
    address = listener.getsockname()

    with pytest.raises(block_socket_connections.error, match="network access is blocked"):
        socket.create_connection(address, timeout=1)

    assert_no_connection(listener)
    assert len(block_socket_connections.attempts) == 1
    block_socket_connections.attempts.clear()


def test_socket_connect_is_blocked(block_socket_connections, listener):
    address = listener.getsockname()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(block_socket_connections.error, match="network access is blocked"):
            client.connect(address)

    assert_no_connection(listener)
    assert len(block_socket_connections.attempts) == 1
    block_socket_connections.attempts.clear()


def test_socket_connect_ex_is_blocked(block_socket_connections, listener):
    address = listener.getsockname()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(block_socket_connections.error, match="network access is blocked"):
            client.connect_ex(address)

    assert_no_connection(listener)
    assert len(block_socket_connections.attempts) == 1
    block_socket_connections.attempts.clear()


def test_blocked_error_is_not_an_os_error(block_socket_connections):
    # Code that handles a network failure catches OSError. The block must not
    # look like a network failure, or that code would hide it.
    assert not issubclass(block_socket_connections.error, OSError)
