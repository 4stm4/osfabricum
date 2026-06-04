"""Firmware blob fetching and ingestion (M11).

``fetch_firmware_blob``
    Download a single firmware file from a URL, optionally verify its
    SHA-256 hash, ingest it into the artifact store, and upsert the
    :class:`~osfabricum.db.models.FirmwareBlob` database row.

``fetch_all_firmware``
    Fetch every ``FirmwareBlob`` record registered for a board whose
    ``metadata_json`` contains a ``url`` field.

Design notes
------------
* HTTP downloads are performed via :func:`urllib.request.urlopen` so no
  extra dependencies are needed.
* Content-address deduplication is handled by
  :func:`~osfabricum.store.ingest.ingest_blob`; a blob that was already
  fetched is returned directly from the store without re-downloading if
  the SHA-256 matches.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact, Board, FirmwareBlob
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob


def fetch_firmware_blob(
    *,
    url: str,
    filename: str,
    board_id: str,
    expected_sha256: str | None = None,
    placement: str = "boot",
    required: bool = True,
    store_root: Path,
    db_url: str | None = None,
) -> FirmwareBlob:
    """Download *url*, verify hash, ingest, and upsert ``FirmwareBlob`` row.

    Parameters
    ----------
    url:
        HTTP/HTTPS URL to download.
    filename:
        Logical filename of the firmware blob (e.g. ``start4.elf``).
    board_id:
        UUID of the :class:`~osfabricum.db.models.Board` this firmware
        belongs to.
    expected_sha256:
        Optional lowercase hex SHA-256 of the expected file content.
        Raises :exc:`ValueError` if the download does not match.
    placement:
        Where the file should be placed on the target (e.g. ``"boot"``).
    required:
        Whether the firmware is mandatory for the board to boot.
    store_root:
        Artifact store root directory.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    FirmwareBlob
        The (possibly newly created or updated) database row.
        The returned object is expunged from the session and safe to use
        outside a transaction.
    """
    with urllib.request.urlopen(url) as resp:  # noqa: S310
        data: bytes = resp.read()

    actual_sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256.lower():
        raise ValueError(
            f"SHA-256 mismatch for {filename}: "
            f"expected {expected_sha256.lower()!r}, got {actual_sha256!r}"
        )

    store_key = f"firmware/{board_id}/{filename}"
    art: Artifact = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=store_key,
        kind="firmware",
        name=filename,
        version="latest",
        media_type="application/octet-stream",
        db_url=db_url,
        retention_class="permanent",
    )

    # Upsert FirmwareBlob row
    fb_row: FirmwareBlob
    if db_url is not None:
        with sync_session(db_url) as session:
            existing: FirmwareBlob | None = session.scalar(
                select(FirmwareBlob).where(
                    FirmwareBlob.board_id == board_id,
                    FirmwareBlob.filename == filename,
                )
            )
            if existing is None:
                fb_row = FirmwareBlob(
                    board_id=board_id,
                    filename=filename,
                    artifact_id=art.id,
                    required=required,
                    placement=placement,
                )
                session.add(fb_row)
            else:
                existing.artifact_id = art.id
                fb_row = existing
            session.commit()
            session.expunge(fb_row)
    else:
        # No DB — return a transient object for testing
        fb_row = FirmwareBlob(
            board_id=board_id,
            filename=filename,
            artifact_id=art.id,
            required=required,
            placement=placement,
        )

    return fb_row


def fetch_all_firmware(
    *,
    board_name: str,
    store_root: Path,
    db_url: str | None = None,
) -> list[FirmwareBlob]:
    """Fetch all firmware blobs registered for *board_name*.

    Only ``FirmwareBlob`` rows whose ``metadata_json`` contains a ``url``
    key are downloaded; rows without a URL are skipped.

    Parameters
    ----------
    board_name:
        Name of the board (e.g. ``"rpi-zero-2w"``).
    store_root:
        Artifact store root directory.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    list[FirmwareBlob]
        Updated rows for every blob that had a URL.
    """
    with sync_session(db_url) as session:
        board: Board | None = session.scalar(select(Board).where(Board.name == board_name))
        if board is None:
            raise ValueError(f"board not found: {board_name!r}")
        board_id = board.id

        blobs = session.scalars(select(FirmwareBlob).where(FirmwareBlob.board_id == board_id)).all()
        blob_meta = [
            (
                b.filename,
                (b.metadata_json or {}).get("url", ""),
                (b.metadata_json or {}).get("sha256"),
                b.placement,
                b.required,
            )
            for b in blobs
        ]

    results: list[FirmwareBlob] = []
    for filename, url, sha256, placement, required in blob_meta:
        if not url:
            continue
        fb = fetch_firmware_blob(
            url=url,
            filename=filename,
            board_id=board_id,
            expected_sha256=sha256,
            placement=placement,
            required=required,
            store_root=store_root,
            db_url=db_url,
        )
        results.append(fb)

    return results
