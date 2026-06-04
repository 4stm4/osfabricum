"""Artifact integrity verification policy (M14).

``verify_artifact_integrity``
    Load an :class:`~osfabricum.db.models.Artifact` row, locate its blob on
    disk, and assert that the on-disk SHA-256 matches the recorded value.
    This is the *verify-on-use* check described in SecuritySettings.

``verify_artifacts``
    Batch version — returns a summary over a list of artifact IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path, compute_sha256


@dataclass
class VerificationResult:
    """Result of one artifact integrity check."""

    ok: bool
    artifact_id: str
    store_key: str
    expected_sha256: str
    actual_sha256: str | None = None
    error: str | None = None


@dataclass
class BatchVerificationResult:
    """Aggregated result of :func:`verify_artifacts`."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: list[VerificationResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.total > 0


def verify_artifact_integrity(
    artifact_id: str,
    store_root: Path,
    *,
    db_url: str | None = None,
) -> VerificationResult:
    """Verify the on-disk blob SHA-256 for a single artifact.

    Parameters
    ----------
    artifact_id:
        UUID of the :class:`~osfabricum.db.models.Artifact` row.
    store_root:
        Root of the content-addressed artifact store.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    VerificationResult
        ``ok=True`` when the on-disk SHA-256 matches the recorded value.
    """
    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(select(Artifact).where(Artifact.id == artifact_id))

    if art is None:
        return VerificationResult(
            ok=False,
            artifact_id=artifact_id,
            store_key="",
            expected_sha256="",
            error=f"artifact not found: {artifact_id!r}",
        )

    bp = blob_path(store_root, art.blob_sha256)
    if not bp.exists():
        return VerificationResult(
            ok=False,
            artifact_id=artifact_id,
            store_key=art.store_key,
            expected_sha256=art.blob_sha256,
            error=f"blob file missing: {bp}",
        )

    actual = compute_sha256(bp.read_bytes())
    if actual != art.blob_sha256:
        return VerificationResult(
            ok=False,
            artifact_id=artifact_id,
            store_key=art.store_key,
            expected_sha256=art.blob_sha256,
            actual_sha256=actual,
            error=f"sha256 mismatch: expected {art.blob_sha256}, got {actual}",
        )

    return VerificationResult(
        ok=True,
        artifact_id=artifact_id,
        store_key=art.store_key,
        expected_sha256=art.blob_sha256,
        actual_sha256=actual,
    )


def verify_artifacts(
    artifact_ids: list[str],
    store_root: Path,
    *,
    db_url: str | None = None,
) -> BatchVerificationResult:
    """Verify a list of artifacts and return an aggregated result."""
    result = BatchVerificationResult(total=len(artifact_ids))
    for aid in artifact_ids:
        vr = verify_artifact_integrity(aid, store_root, db_url=db_url)
        if vr.ok:
            result.passed += 1
        else:
            result.failed += 1
            result.errors.append(vr)
    return result
