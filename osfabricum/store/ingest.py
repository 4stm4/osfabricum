"""Blob ingest into the content-addressed store."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path, compute_sha256, ref_path

if TYPE_CHECKING:
    from osfabricum.repro.chain import ReproRecord


def ingest_blob(
    data: bytes,
    store_root: Path,
    store_key: str,
    kind: str,
    name: str,
    version: str | None = None,
    arch: str | None = None,
    expected_sha256: str | None = None,
    db_url: str | None = None,
    retention_class: str = "staging",
    media_type: str | None = None,
    input_hash: str | None = None,
    repro_record: ReproRecord | None = None,
) -> Artifact:
    """Write *data* into the store and create an Artifact metadata row.

    If *expected_sha256* is given and does not match the computed digest the
    blob is rejected and ``ValueError`` is raised — the store is not modified.

    If a blob with the same sha256 already exists it is not written again
    (content-dedup). If an Artifact row already exists for *store_key* it is
    returned unchanged.

    Parameters
    ----------
    input_hash:
        SHA-256 hex of the :class:`~osfabricum.repro.chain.InputManifest`
        that produced this blob.  Stored in ``Artifact.input_hash`` for
        traceability (M13).
    repro_record:
        Full :class:`~osfabricum.repro.chain.ReproRecord`.  When provided
        it is serialized and merged into ``Artifact.metadata_json["repro"]``.
    """
    actual_sha256 = compute_sha256(data)
    if expected_sha256 is not None and expected_sha256 != actual_sha256:
        raise ValueError(
            f"sha256 mismatch for '{store_key}': expected {expected_sha256}, got {actual_sha256}"
        )

    dest = blob_path(store_root, actual_sha256)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    ref = ref_path(store_root, store_key)
    ref.parent.mkdir(parents=True, exist_ok=True)
    if ref.exists() or ref.is_symlink():
        ref.unlink()
    ref.symlink_to(dest)

    metadata: dict | None = None
    if repro_record is not None:
        metadata = {"repro": repro_record.to_dict()}

    with sync_session(db_url) as session:
        existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
        if existing is not None:
            if existing.blob_sha256 == actual_sha256:
                return existing
            # Content changed — update the row in-place so the store_key always
            # reflects the current blob (mutable store keys like composed rootfs/image).
            existing.blob_sha256 = actual_sha256
            existing.size_bytes = len(data)
            if input_hash is not None:
                existing.input_hash = input_hash
            if repro_record is not None:
                existing.metadata_json = {"repro": repro_record.to_dict()}
            session.commit()
            session.refresh(existing)
            return existing
        artifact = Artifact(
            kind=kind,
            name=name,
            version=version,
            arch=arch,
            store_key=store_key,
            blob_sha256=actual_sha256,
            size_bytes=len(data),
            media_type=media_type,
            retention_class=retention_class,
            input_hash=input_hash,
            metadata_json=metadata,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact
