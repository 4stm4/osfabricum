"""Source fetch and cache logic (M7).

``fetch_source`` is the single entry point for downloading a registered
source entry, verifying its sha256, and ingesting it into the artifact store.
Subsequent calls for the same source are served from the cache without
re-downloading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Artifact, Source
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import compute_sha256

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_source(identifier: str, db_url: str | None) -> Source:
    """Return a :class:`Source` by URI, id, or ``metadata_json["name"]``.

    Raises:
        ValueError: when no matching source is found.
    """
    with sync_session(db_url) as session:
        # 1. Exact URI match
        src = session.scalar(select(Source).where(Source.uri == identifier))
        if src is not None:
            session.expunge(src)
            return src
        # 2. Primary key (UUID)
        src = session.scalar(select(Source).where(Source.id == identifier))
        if src is not None:
            session.expunge(src)
            return src
        # 3. Metadata name (scan — table is small)
        for s in session.scalars(select(Source)).all():
            if (s.metadata_json or {}).get("name") == identifier:
                session.expunge(s)
                return s
    raise ValueError(f"source not found: {identifier!r}")


def _store_key(source_id: str, source_type: str, uri: str, ref: str | None) -> str:
    """Derive a deterministic store key for a source record."""
    if source_type == "git":
        filename = f"{ref or 'archive'}.tar.gz"
    else:
        filename = uri.rsplit("/", 1)[-1] or "archive"
    return f"source/{source_id}/{filename}"


def _media_type_for(filename: str) -> str:
    if filename.endswith((".tar.gz", ".tgz")):
        return "application/x-gzip"
    if filename.endswith(".tar.bz2"):
        return "application/x-bzip2"
    if filename.endswith(".tar.zst"):
        return "application/zstd"
    if filename.endswith(".zip"):
        return "application/zip"
    return "application/octet-stream"


def _normalise_hash(raw: str) -> str:
    """Strip an optional ``sha256:`` prefix from a stored hash string."""
    return raw[7:] if raw.startswith("sha256:") else raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_source(
    source_uri_or_id: str,
    store_root: Path,
    db_url: str | None = None,
    *,
    offline: bool = False,
) -> str:
    """Fetch a registered source and return the resulting artifact id.

    Steps
    -----
    1. Look up the :class:`~osfabricum.db.models.Source` record.
    2. Check whether the artifact is already in the store (**cache hit**).
    3. In **offline** mode, raise ``RuntimeError`` on a cache miss.
    4. Download the source according to ``source_type`` (``http``/``https``
       or ``git``).
    5. Verify the downloaded bytes against ``expected_hash`` if set.
    6. Ingest via :func:`~osfabricum.store.ingest.ingest_blob`.
    7. Return ``Artifact.id``.

    Parameters
    ----------
    source_uri_or_id:
        Full URI, source UUID, or the ``name`` stored in
        ``metadata_json["name"]``.
    store_root:
        Root of the content-addressed artifact store.
    db_url:
        SQLAlchemy database URL.  Uses the default settings URL when ``None``.
    offline:
        When ``True``, only serve from cache — never make network requests.

    Raises
    ------
    ValueError:
        Source not found, unsupported ``source_type``, or sha256 mismatch.
    RuntimeError:
        Cache miss in offline mode.
    """
    src = _lookup_source(source_uri_or_id, db_url)
    store_key = _store_key(src.id, src.source_type, src.uri, src.ref)

    # --- cache check ---
    with sync_session(db_url) as session:
        existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
        if existing is not None:
            return existing.id

    if offline:
        raise RuntimeError(f"source not in cache (offline mode): {source_uri_or_id!r}")

    # --- download ---
    meta: dict[str, Any] = dict(src.metadata_json or {})
    if src.source_type == "git":
        from osfabricum.fetcher.git import fetch_git_archive

        data = fetch_git_archive(src.uri, src.ref or "main", meta)
    elif src.source_type in ("http", "https"):
        from osfabricum.fetcher.http import fetch_http

        data = fetch_http(src.uri)
    else:
        raise ValueError(f"unsupported source_type: {src.source_type!r}")

    # --- sha256 verification ---
    actual_sha256 = compute_sha256(data)
    if src.expected_hash:
        expected = _normalise_hash(src.expected_hash)
        if actual_sha256 != expected:
            raise ValueError(
                f"sha256 mismatch for source {src.uri!r}: expected {expected}, got {actual_sha256}"
            )

    # --- ingest ---
    filename = store_key.rsplit("/", 1)[-1]
    display_name = str(meta.get("name") or src.uri.rsplit("/", 1)[-1])
    artifact = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=store_key,
        kind="source",
        name=display_name,
        version=src.ref,
        media_type=_media_type_for(filename),
        db_url=db_url,
        retention_class="cache-hot",
    )
    return artifact.id
