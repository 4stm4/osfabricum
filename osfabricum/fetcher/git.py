"""Git source fetch — clone at *ref* and produce a tar.gz archive (M7).

Two code paths:
1. **Fast path** (preferred): if ``metadata["tarball_url"]`` is set, download
   the pre-made tarball from the forge over HTTP.  No ``git`` binary needed.
   GitHub, Gitea, etc. all expose ``/archive/<ref>.tar.gz`` endpoints.

2. **Fallback**: ``git clone --depth 1 --branch <ref>`` to a temporary
   directory and tar the result.  Requires ``git`` on ``PATH``.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from typing import Any


def fetch_git_archive(
    uri: str,
    ref: str,
    metadata: dict[str, Any] | None = None,
) -> bytes:
    """Return a ``.tar.gz`` of the source tree at *ref*.

    If *metadata* contains a ``"tarball_url"`` key the archive is downloaded
    via HTTP instead of cloning the repository.
    """
    tarball_url = str((metadata or {}).get("tarball_url") or "")
    if tarball_url:
        from osfabricum.fetcher.http import fetch_http

        return fetch_http(tarball_url)

    # --- subprocess git clone fallback ---
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(  # noqa: S603
            ["git", "clone", "--depth=1", "--branch", ref, "--", uri, tmp],
            check=True,
            capture_output=True,
        )
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(tmp, arcname="source")
        return buf.getvalue()
