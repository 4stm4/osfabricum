"""Overlay build and application (M11).

An *overlay* is a tar.gz archive that, when extracted over a rootfs
directory, patches files into place (``/etc``, ``/usr/local/bin``, etc.).

``build_overlay``
    Pack a local directory tree into a tar.gz, ingest it as an artifact,
    and upsert the :class:`~osfabricum.db.models.Overlay` database row.

``apply_overlay``
    Fetch an overlay artifact and extract it into a target directory.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact, Overlay
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob


def build_overlay(
    *,
    name: str,
    src_dir: Path,
    store_root: Path,
    distribution_id: str | None = None,
    profile_id: str | None = None,
    board_id: str | None = None,
    db_url: str | None = None,
) -> Artifact:
    """Pack *src_dir* into a tar.gz overlay and store it as an artifact.

    Parameters
    ----------
    name:
        Human-readable overlay name (used as the ``Overlay.name`` row).
    src_dir:
        Source directory to pack.  The archive root maps to ``/`` on the
        target rootfs.
    store_root:
        Artifact store root directory.
    distribution_id, profile_id, board_id:
        Optional FK references written into the ``overlays`` table row.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    Artifact
        The ingested artifact row.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(src_dir.rglob("*")):
            arcname = str(item.relative_to(src_dir))
            tar.add(str(item), arcname=arcname)
    data = buf.getvalue()

    store_key = f"overlay/{name}"
    art = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=store_key,
        kind="overlay",
        name=name,
        version="latest",
        media_type="application/x-gzip",
        db_url=db_url,
        retention_class="permanent",
    )

    # Upsert Overlay row
    if db_url is not None:
        with sync_session(db_url) as session:
            existing: Overlay | None = session.scalar(select(Overlay).where(Overlay.name == name))
            if existing is None:
                session.add(
                    Overlay(
                        name=name,
                        distribution_id=distribution_id,
                        profile_id=profile_id,
                        board_id=board_id,
                        artifact_id=art.id,
                    )
                )
            else:
                existing.artifact_id = art.id
            session.commit()

    return art


def apply_overlay(
    *,
    artifact_id: str,
    target_dir: Path,
    store_root: Path,
    db_url: str | None = None,
) -> list[str]:
    """Extract an overlay artifact into *target_dir*.

    Parameters
    ----------
    artifact_id:
        UUID of the ``Artifact`` row for this overlay.
    target_dir:
        Destination rootfs directory.  Created if it does not exist.
    store_root:
        Artifact store root directory.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    list[str]
        List of relative paths that were extracted.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # Locate blob on disk
    blob_sha256: str = ""
    if db_url is not None:
        with sync_session(db_url) as session:
            art: Artifact | None = session.scalar(
                select(Artifact).where(Artifact.id == artifact_id)
            )
            if art is None:
                raise ValueError(f"artifact not found: {artifact_id!r}")
            blob_sha256 = art.blob_sha256
    else:
        raise ValueError("db_url is required for apply_overlay")

    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, blob_sha256)
    if not bp.exists():
        raise FileNotFoundError(f"overlay blob not found at {bp}")

    extracted: list[str] = []
    with tarfile.open(str(bp), mode="r:gz") as tar:
        members = tar.getmembers()
        tar.extractall(path=str(target_dir), filter="data")
        extracted = [m.name for m in members if m.isfile()]

    return extracted
