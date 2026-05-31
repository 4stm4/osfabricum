"""Verify all stored blobs against their recorded sha256."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path, compute_sha256


def verify_store(store_root: Path, db_url: str | None = None) -> tuple[int, list[str]]:
    """Check every Artifact row against the blob on disk.

    Returns ``(ok_count, errors)`` where *errors* is a list of human-readable
    problem descriptions.  An empty store (no Artifact rows) returns ``(0, [])``.
    """
    ok = 0
    errors: list[str] = []
    with sync_session(db_url) as session:
        artifacts = session.scalars(select(Artifact)).all()
    for artifact in artifacts:
        dest = blob_path(store_root, artifact.blob_sha256)
        if not dest.exists():
            errors.append(
                f"{artifact.store_key}: blob file missing (sha256={artifact.blob_sha256})"
            )
            continue
        actual = compute_sha256(dest.read_bytes())
        if actual != artifact.blob_sha256:
            errors.append(
                f"{artifact.store_key}: sha256 mismatch "
                f"(expected {artifact.blob_sha256}, got {actual})"
            )
        else:
            ok += 1
    return ok, errors
