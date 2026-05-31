"""Plain HTTP/HTTPS source download (M7)."""

from __future__ import annotations

import urllib.request


def fetch_http(uri: str) -> bytes:
    """Download *uri* and return the raw bytes.

    Follows redirects automatically (urllib default behaviour).
    Raises ``urllib.error.URLError`` on network errors.
    """
    with urllib.request.urlopen(uri) as resp:  # noqa: S310
        return resp.read()  # type: ignore[no-any-return]
