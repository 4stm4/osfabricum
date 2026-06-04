"""Artifact store garbage collection (M23).

``collect_garbage``
    Delete age-expired, unpinned artifacts (per the retention policy),
    optionally enforce a ``cache-hot`` quota via LRU eviction, then sweep
    orphaned blob files no longer referenced by any artifact.

``store_stats``
    Summarize the store: artifact / byte counts per retention class, plus
    total on-disk blob size and orphan count.

``pin_artifact`` / ``unpin_artifact``
    Toggle the ``pinned`` flag (pinned artifacts are never GC'd).

Content-addressed safety
------------------------
Blobs are deduplicated by SHA-256: several artifacts may reference the same
blob file.  A blob file is only removed when **no** remaining artifact row
references its SHA-256.  All deletions honour ``dry_run``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path, ref_path
from osfabricum.store.retention import is_expired


@dataclass
class GcResult:
    """Outcome of a :func:`collect_garbage` run."""

    dry_run: bool
    deleted_artifacts: list[str] = field(default_factory=list)
    removed_blobs: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    orphan_blobs_removed: int = 0
    kept_artifacts: int = 0
    logs: list[str] = field(default_factory=list)


@dataclass
class StoreStats:
    """Summary of store contents."""

    total_artifacts: int = 0
    total_bytes: int = 0
    by_class: dict[str, dict[str, int]] = field(default_factory=dict)
    pinned: int = 0
    blob_files: int = 0
    orphan_blobs: int = 0


# ---------------------------------------------------------------------------
# Pin / unpin
# ---------------------------------------------------------------------------


def pin_artifact(artifact_id: str, *, db_url: str | None = None) -> bool:
    """Set ``pinned=True``.  Returns ``True`` if the artifact existed."""
    return _set_pinned(artifact_id, True, db_url)


def unpin_artifact(artifact_id: str, *, db_url: str | None = None) -> bool:
    """Set ``pinned=False``.  Returns ``True`` if the artifact existed."""
    return _set_pinned(artifact_id, False, db_url)


def _set_pinned(artifact_id: str, value: bool, db_url: str | None) -> bool:
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
        if art is None:
            return False
        art.pinned = value
        session.commit()
        return True


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def store_stats(store_root: Path, *, db_url: str | None = None) -> StoreStats:
    """Return a :class:`StoreStats` summary of the store."""
    stats = StoreStats()
    referenced: set[str] = set()

    with sync_session(db_url) as session:
        artifacts = session.scalars(select(Artifact)).all()
        for art in artifacts:
            stats.total_artifacts += 1
            size = art.size_bytes or 0
            stats.total_bytes += size
            if art.pinned:
                stats.pinned += 1
            referenced.add(art.blob_sha256)
            bucket = stats.by_class.setdefault(art.retention_class, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += size

    # On-disk blob accounting
    blobs_dir = store_root / "blobs" / "sha256"
    if blobs_dir.is_dir():
        for blob_file in blobs_dir.rglob("*"):
            if blob_file.is_file():
                stats.blob_files += 1
                if blob_file.name not in referenced:
                    stats.orphan_blobs += 1

    return stats


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------


def _blob_refcount(session, blob_sha256: str) -> int:
    """Number of Artifact rows referencing *blob_sha256*."""
    return (
        session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.blob_sha256 == blob_sha256)
        )
        or 0
    )


def collect_garbage(
    store_root: Path,
    *,
    db_url: str | None = None,
    dry_run: bool = False,
    quota_bytes: int | None = None,
    now: datetime | None = None,
) -> GcResult:
    """Garbage-collect the artifact store.

    Steps
    -----
    1. Delete age-expired, unpinned artifacts (per retention policy).
    2. If *quota_bytes* is set, evict ``cache-hot`` artifacts LRU-style
       (oldest first) until the total ``cache-hot`` size fits the quota.
    3. Remove blob files that no artifact references any more.
    4. Sweep orphan blob files (no DB row at all).

    Parameters
    ----------
    store_root:
        Artifact store root.
    db_url:
        SQLAlchemy database URL.
    dry_run:
        Report what would be deleted without touching the DB or disk.
    quota_bytes:
        Optional byte budget for the ``cache-hot`` class.
    now:
        Reference time for expiry (testing).
    """
    result = GcResult(dry_run=dry_run)

    with sync_session(db_url) as session:
        artifacts = session.scalars(select(Artifact)).all()

        # --- 1. age-based expiry ---
        to_delete: list[Artifact] = []
        for art in artifacts:
            if is_expired(
                art.retention_class,
                art.created_at,
                pinned=art.pinned,
                now=now,
            ):
                to_delete.append(art)
            else:
                result.kept_artifacts += 1

        # --- 2. cache-hot quota (LRU) ---
        if quota_bytes is not None:
            hot = [
                a
                for a in artifacts
                if a.retention_class == "cache-hot" and not a.pinned and a not in to_delete
            ]
            hot.sort(key=lambda a: a.created_at or datetime.min)  # oldest first
            hot_total = sum(a.size_bytes or 0 for a in hot)
            for art in hot:
                if hot_total <= quota_bytes:
                    break
                to_delete.append(art)
                # This artifact was counted as "kept" in step 1; un-count it.
                result.kept_artifacts = max(0, result.kept_artifacts - 1)
                hot_total -= art.size_bytes or 0

        # --- 3. delete artifacts + dereference blobs ---
        for art in to_delete:
            result.deleted_artifacts.append(art.id)
            result.freed_bytes += art.size_bytes or 0
            result.logs.append(
                f"[gc] expire {art.kind}/{art.name} ({art.retention_class}, {art.id[:8]}…)"
            )

            if not dry_run:
                # Remove the human-readable ref symlink
                ref = ref_path(store_root, art.store_key)
                if ref.exists() or ref.is_symlink():
                    ref.unlink()

                # Remove blob only if this was the last reference
                refcount = _blob_refcount(session, art.blob_sha256)
                if refcount <= 1:
                    bp = blob_path(store_root, art.blob_sha256)
                    if bp.exists():
                        bp.unlink()
                        result.removed_blobs.append(art.blob_sha256)

                session.delete(art)

        if not dry_run:
            session.commit()

        # --- 4. orphan blob sweep ---
        # Recompute referenced set AFTER deletions.
        remaining = session.scalars(select(Artifact.blob_sha256)).all()
        referenced = set(remaining)

    blobs_dir = store_root / "blobs" / "sha256"
    if blobs_dir.is_dir():
        for blob_file in blobs_dir.rglob("*"):
            if blob_file.is_file() and blob_file.name not in referenced:
                result.orphan_blobs_removed += 1
                result.logs.append(f"[gc] orphan blob {blob_file.name[:16]}…")
                if not dry_run:
                    try:
                        result.freed_bytes += blob_file.stat().st_size
                        blob_file.unlink()
                    except OSError:
                        pass

    result.logs.append(
        f"[gc] {'(dry-run) ' if dry_run else ''}"
        f"deleted {len(result.deleted_artifacts)} artifact(s), "
        f"removed {len(result.removed_blobs)} blob(s), "
        f"swept {result.orphan_blobs_removed} orphan(s), "
        f"freed {result.freed_bytes} bytes"
    )
    return result
