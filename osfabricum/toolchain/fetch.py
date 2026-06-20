"""Toolchain tarball fetch and store (M6).

``fetch_toolchain`` downloads a prebuilt toolchain from the URL stored in
the toolchain's ``metadata_json["download_url"]``, ingests the blob into the
content-addressed store, and creates a :class:`~osfabricum.db.models.ToolchainArtifact`
linking the toolchain record to the stored artifact.

``fetch_and_extract_toolchain`` additionally extracts the tarball to a local
directory so the toolchain binaries are directly usable by kernel/package
build steps.
"""

from __future__ import annotations

import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact, Toolchain, ToolchainArtifact
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def fetch_toolchain(
    toolchain_name_or_id: str,
    store_root: Path,
    db_url: str | None = None,
) -> str:
    """Download a toolchain tarball, store it, and return the artifact id.

    The function performs the following steps:

    1. Look up the :class:`~osfabricum.db.models.Toolchain` by *name* (falling
       back to ``id`` when the name is not found).
    2. Read the download URL from ``metadata_json["download_url"]``.
    3. Download the tarball via ``urllib.request.urlopen``.
    4. Ingest the blob into the content-addressed store via
       :func:`~osfabricum.store.ingest.ingest_blob`.
    5. Create a :class:`~osfabricum.db.models.ToolchainArtifact` row (skipped
       if one already exists for the toolchain).
    6. Return the ``Artifact.id`` of the stored tarball.

    Raises:
        ValueError: if the toolchain is not found or has no download URL.
    """
    # --- 1. resolve toolchain record ---
    with sync_session(db_url) as session:
        tc: Toolchain | None = session.scalar(
            select(Toolchain).where(Toolchain.name == toolchain_name_or_id)
        )
        if tc is None:
            tc = session.scalar(select(Toolchain).where(Toolchain.id == toolchain_name_or_id))
        if tc is None:
            raise ValueError(f"toolchain not found: {toolchain_name_or_id!r}")
        tc_id = tc.id
        tc_name = tc.name
        tc_version = tc.version
        meta: dict[str, object] = dict(tc.metadata_json or {})

    download_url = str(meta.get("download_url") or "")
    if not download_url:
        raise ValueError(f"toolchain {tc_name!r} has no 'download_url' in metadata_json")

    # --- 2. download ---
    with urllib.request.urlopen(download_url) as resp:  # noqa: S310
        data: bytes = resp.read()

    # --- 3. ingest ---
    filename = download_url.rsplit("/", 1)[-1]
    store_key = f"toolchain/{tc_name}/{tc_version}/{filename}"
    artifact: Artifact = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=store_key,
        kind="toolchain",
        name=tc_name,
        version=tc_version,
        media_type="application/x-bzip2",
        db_url=db_url,
        retention_class="permanent",
    )

    # --- 4. link toolchain → artifact ---
    with sync_session(db_url) as session:
        existing = session.scalar(
            select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc_id)
        )
        if existing is None:
            session.add(
                ToolchainArtifact(
                    toolchain_id=tc_id,
                    artifact_id=artifact.id,
                    verified_at=_now(),
                )
            )
            session.commit()

    return artifact.id


def fetch_and_extract_toolchain(
    toolchain_name_or_id: str,
    store_root: Path,
    db_url: str | None = None,
) -> Path:
    """Fetch a toolchain (if not already stored) and extract it for use.

    Returns the path to the extracted toolchain root — the directory that
    contains ``bin/`` with the cross-compiler binaries.  Subsequent calls
    with the same toolchain are instant (idempotent: skip download if artifact
    exists, skip extraction if directory already present).
    """
    # Resolve toolchain name so we can build a stable extract path.
    with sync_session(db_url) as session:
        tc: Toolchain | None = session.scalar(
            select(Toolchain).where(Toolchain.name == toolchain_name_or_id)
        )
        if tc is None:
            tc = session.scalar(select(Toolchain).where(Toolchain.id == toolchain_name_or_id))
        if tc is None:
            raise ValueError(f"toolchain not found: {toolchain_name_or_id!r}")
        tc_name = tc.name
        tc_version = tc.version
        tc_id = tc.id
        meta: dict[str, object] = dict(tc.metadata_json or {})

    extract_dir = store_root / "toolchains" / tc_name
    # Return immediately if already extracted (idempotent).
    if extract_dir.exists():
        root = _find_toolchain_root(extract_dir)
        if root is not None:
            return root

    # Fetch the blob (download + ingest) if not already in the store.
    with sync_session(db_url) as session:
        existing_ta = session.scalar(
            select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc_id)
        )
        if existing_ta is not None:
            artifact = session.get(Artifact, existing_ta.artifact_id)
            blob = blob_path(store_root, artifact.sha256) if artifact else None
        else:
            blob = None

    if blob is None or not blob.exists():
        # Need to download.
        download_url = str(meta.get("download_url") or "")
        if not download_url:
            raise ValueError(f"toolchain {tc_name!r} has no 'download_url' in metadata_json")
        with urllib.request.urlopen(download_url) as resp:  # noqa: S310
            data: bytes = resp.read()
        filename = download_url.rsplit("/", 1)[-1]
        store_key = f"toolchain/{tc_name}/{tc_version}/{filename}"
        artifact = ingest_blob(
            data=data,
            store_root=store_root,
            store_key=store_key,
            kind="toolchain",
            name=tc_name,
            version=tc_version,
            media_type="application/x-bzip2",
            db_url=db_url,
            retention_class="permanent",
        )
        with sync_session(db_url) as session:
            if session.scalar(
                select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc_id)
            ) is None:
                session.add(
                    ToolchainArtifact(
                        toolchain_id=tc_id,
                        artifact_id=artifact.id,
                        verified_at=_now(),
                    )
                )
                session.commit()
        blob = blob_path(store_root, artifact.sha256)

    # Extract tarball.
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(blob), mode="r:*") as tar:
        tar.extractall(path=str(extract_dir), filter="data")

    root = _find_toolchain_root(extract_dir)
    if root is None:
        raise RuntimeError(f"could not locate bin/ inside extracted toolchain at {extract_dir}")
    return root


def _find_toolchain_root(base: Path) -> Path | None:
    """Return the directory inside *base* that contains a ``bin/`` subdirectory."""
    if (base / "bin").is_dir():
        return base
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "bin").is_dir():
            return child
    return None
