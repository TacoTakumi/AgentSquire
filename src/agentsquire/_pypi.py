"""The one network step of the release check.

fetch is the only function in the package that opens a URL. It makes one
HTTPS GET with a User-Agent that names agentsquire and its version, a short
socket timeout and a fixed limit on the size of the body. It does not catch
network errors: the caller turns an OSError or a ValueError into a result.
"""

from __future__ import annotations

import urllib.request
from typing import Any

from agentsquire import __version__

# Seconds allowed for each blocking socket operation (connect, each read).
SOCKET_TIMEOUT = 3.0

# The largest response body that fetch returns. A larger body is an error.
MAX_BYTES = 4 * 1024 * 1024

USER_AGENT = f"agentsquire/{__version__}"


def _open(request: urllib.request.Request, timeout: float) -> Any:
    """Open the request. The single seam that a test replaces."""
    return urllib.request.urlopen(request, timeout=timeout)


def fetch(url: str) -> bytes:
    """Return the body of an HTTPS GET of ``url``.

    Raises ValueError for a URL that is not https or for a body larger than
    MAX_BYTES. Lets every OSError (URLError, HTTPError, a timeout, a TLS
    error) propagate.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"not an https URL: {url!r}")
    # No Accept-Encoding header: the body arrives as plain bytes, so the
    # size limit applies to the data that is read.
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response = _open(request, SOCKET_TIMEOUT)
    try:
        body = response.read(MAX_BYTES + 1)
    finally:
        response.close()
    if len(body) > MAX_BYTES:
        raise ValueError(f"response body is larger than {MAX_BYTES} bytes")
    return body
