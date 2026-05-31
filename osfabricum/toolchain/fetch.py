"""Toolchain tarball fetch and store (M6).

``fetch_toolchain`` downloads a prebuilt toolchain from the URL stored in
the toolchain's ``metadata_json["download_url"]``, ingests the blob into the
content-addressed store, and creates a :class:`~osfabricum.db.models.ToolchainArtifact`
linking the toolchain record to the stored artifact.
"""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact, Toolchain, ToolchainArtifact
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob


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
            tc = session.scalar(
                select(Toolchain).where(Toolchain.id == toolchain_name_or_id)
            )
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
