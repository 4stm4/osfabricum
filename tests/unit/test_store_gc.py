"""Tests for M23: Store GC / Retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Artifact, Base
from osfabricum.db.session import sync_session
from osfabricum.store.gc import (
    collect_garbage,
    pin_artifact,
    store_stats,
    unpin_artifact,
)
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path
from osfabricum.store.retention import (
    PROTECTED_CLASSES,
    RETENTION_POLICY,
    is_expired,
    retention_age_days,
)

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ingest(
    db_url: str,
    store_root: Path,
    *,
    data: bytes,
    key: str,
    retention: str,
    age_days: int = 0,
    pinned: bool = False,
) -> Artifact:
    """Ingest an artifact and back-date its created_at by *age_days*."""
    art = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=key,
        kind="test",
        name=key.replace("/", "-"),
        retention_class=retention,
        db_url=db_url,
    )
    if age_days or pinned:
        with sync_session(db_url) as session:
            row = session.scalar(select(Artifact).where(Artifact.id == art.id))
            if age_days:
                row.created_at = _now() - timedelta(days=age_days)
            if pinned:
                row.pinned = True
            session.commit()
    return art


# ---------------------------------------------------------------------------
# retention policy
# ---------------------------------------------------------------------------


def test_retention_policy_has_classes() -> None:
    for cls in ("release", "staging", "cache-hot", "cache-cold", "failed-run"):
        assert cls in RETENTION_POLICY


def test_protected_classes_indefinite() -> None:
    assert "release" in PROTECTED_CLASSES
    assert retention_age_days("release") is None


def test_retention_age_staging() -> None:
    assert retention_age_days("staging") == 90


def test_retention_age_unknown_default() -> None:
    assert retention_age_days("totally-unknown") == 90


def test_is_expired_pinned_never() -> None:
    old = _now() - timedelta(days=1000)
    assert is_expired("staging", old, pinned=True) is False


def test_is_expired_protected_never() -> None:
    old = _now() - timedelta(days=10000)
    assert is_expired("release", old) is False
    assert is_expired("promoted", old) is False
    assert is_expired("permanent", old) is False


def test_is_expired_staging_old() -> None:
    old = _now() - timedelta(days=100)
    assert is_expired("staging", old) is True


def test_is_expired_staging_fresh() -> None:
    fresh = _now() - timedelta(days=10)
    assert is_expired("staging", fresh) is False


def test_is_expired_cache_hot_boundary() -> None:
    assert is_expired("cache-hot", _now() - timedelta(days=31)) is True
    assert is_expired("cache-hot", _now() - timedelta(days=5)) is False


def test_is_expired_no_created_at() -> None:
    assert is_expired("staging", None) is False


# ---------------------------------------------------------------------------
# store_stats
# ---------------------------------------------------------------------------


def test_store_stats_empty(db_url: str, store_root: Path) -> None:
    stats = store_stats(store_root, db_url=db_url)
    assert stats.total_artifacts == 0
    assert stats.total_bytes == 0


def test_store_stats_counts(db_url: str, store_root: Path) -> None:
    _ingest(db_url, store_root, data=b"a" * 100, key="t/1", retention="staging")
    _ingest(db_url, store_root, data=b"b" * 200, key="t/2", retention="release")
    stats = store_stats(store_root, db_url=db_url)
    assert stats.total_artifacts == 2
    assert stats.total_bytes == 300
    assert stats.by_class["staging"]["count"] == 1
    assert stats.by_class["release"]["bytes"] == 200


def test_store_stats_pinned_count(db_url: str, store_root: Path) -> None:
    _ingest(db_url, store_root, data=b"x" * 10, key="t/p", retention="staging", pinned=True)
    stats = store_stats(store_root, db_url=db_url)
    assert stats.pinned == 1


# ---------------------------------------------------------------------------
# collect_garbage — age expiry
# ---------------------------------------------------------------------------


def test_gc_deletes_expired_staging(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"old" * 50,
        key="t/old",
        retention="staging",
        age_days=100,
    )
    result = collect_garbage(store_root, db_url=db_url)
    assert art.id in result.deleted_artifacts
    # Artifact row gone
    with sync_session(db_url) as session:
        assert session.scalar(select(Artifact).where(Artifact.id == art.id)) is None
    # Blob gone
    assert not blob_path(store_root, art.blob_sha256).exists()


def test_gc_keeps_fresh_staging(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"new" * 50,
        key="t/new",
        retention="staging",
        age_days=5,
    )
    result = collect_garbage(store_root, db_url=db_url)
    assert art.id not in result.deleted_artifacts
    assert result.kept_artifacts == 1


def test_gc_keeps_release_forever(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"rel" * 50,
        key="t/rel",
        retention="release",
        age_days=10000,
    )
    result = collect_garbage(store_root, db_url=db_url)
    assert art.id not in result.deleted_artifacts


def test_gc_keeps_pinned(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"pin" * 50,
        key="t/pin",
        retention="staging",
        age_days=1000,
        pinned=True,
    )
    result = collect_garbage(store_root, db_url=db_url)
    assert art.id not in result.deleted_artifacts


def test_gc_dry_run_changes_nothing(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"old" * 50,
        key="t/old",
        retention="staging",
        age_days=100,
    )
    result = collect_garbage(store_root, db_url=db_url, dry_run=True)
    assert art.id in result.deleted_artifacts  # reported
    # ...but still present
    with sync_session(db_url) as session:
        assert session.scalar(select(Artifact).where(Artifact.id == art.id)) is not None
    assert blob_path(store_root, art.blob_sha256).exists()


def test_gc_freed_bytes(db_url: str, store_root: Path) -> None:
    _ingest(
        db_url,
        store_root,
        data=b"z" * 500,
        key="t/z",
        retention="cache-cold",
        age_days=30,
    )
    result = collect_garbage(store_root, db_url=db_url)
    assert result.freed_bytes >= 500


# ---------------------------------------------------------------------------
# collect_garbage — shared blobs (dedup safety)
# ---------------------------------------------------------------------------


def test_gc_shared_blob_not_removed_while_referenced(db_url: str, store_root: Path) -> None:
    """Two artifacts share a blob; expiring one must NOT delete the blob."""
    same = b"shared-content" * 100
    old = _ingest(db_url, store_root, data=same, key="t/old", retention="staging", age_days=100)
    fresh = _ingest(db_url, store_root, data=same, key="t/fresh", retention="staging", age_days=1)
    # Both reference the same sha256
    assert old.blob_sha256 == fresh.blob_sha256

    result = collect_garbage(store_root, db_url=db_url)
    assert old.id in result.deleted_artifacts
    # Blob still on disk because 'fresh' references it
    assert blob_path(store_root, old.blob_sha256).exists()
    assert old.blob_sha256 not in result.removed_blobs


# ---------------------------------------------------------------------------
# collect_garbage — orphan sweep
# ---------------------------------------------------------------------------


def test_gc_sweeps_orphan_blob(db_url: str, store_root: Path) -> None:
    # Create a blob file with no Artifact row pointing at it
    orphan_sha = "f" * 64
    bp = blob_path(store_root, orphan_sha)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(b"orphaned data")

    result = collect_garbage(store_root, db_url=db_url)
    assert result.orphan_blobs_removed == 1
    assert not bp.exists()


def test_gc_orphan_dry_run_keeps(db_url: str, store_root: Path) -> None:
    orphan_sha = "e" * 64
    bp = blob_path(store_root, orphan_sha)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(b"orphan")
    result = collect_garbage(store_root, db_url=db_url, dry_run=True)
    assert result.orphan_blobs_removed == 1
    assert bp.exists()  # not actually removed


# ---------------------------------------------------------------------------
# collect_garbage — cache-hot quota (LRU)
# ---------------------------------------------------------------------------


def test_gc_quota_evicts_oldest(db_url: str, store_root: Path) -> None:
    # Three cache-hot artifacts, 1000 bytes each, all fresh.  Quota=2500
    # → must evict the single oldest to fit.
    a1 = _ingest(db_url, store_root, data=b"1" * 1000, key="c/1", retention="cache-hot", age_days=3)
    a2 = _ingest(db_url, store_root, data=b"2" * 1000, key="c/2", retention="cache-hot", age_days=2)
    a3 = _ingest(db_url, store_root, data=b"3" * 1000, key="c/3", retention="cache-hot", age_days=1)
    result = collect_garbage(store_root, db_url=db_url, quota_bytes=2500)
    # Oldest (a1) evicted; a2/a3 kept
    assert a1.id in result.deleted_artifacts
    assert a2.id not in result.deleted_artifacts
    assert a3.id not in result.deleted_artifacts


def test_gc_quota_not_exceeded_no_eviction(db_url: str, store_root: Path) -> None:
    _ingest(db_url, store_root, data=b"1" * 500, key="c/1", retention="cache-hot", age_days=1)
    result = collect_garbage(store_root, db_url=db_url, quota_bytes=10000)
    assert result.deleted_artifacts == []


# ---------------------------------------------------------------------------
# pin / unpin
# ---------------------------------------------------------------------------


def test_pin_artifact(db_url: str, store_root: Path) -> None:
    art = _ingest(db_url, store_root, data=b"p", key="t/p", retention="staging")
    assert pin_artifact(art.id, db_url=db_url) is True
    with sync_session(db_url) as session:
        row = session.scalar(select(Artifact).where(Artifact.id == art.id))
        assert row.pinned is True


def test_unpin_artifact(db_url: str, store_root: Path) -> None:
    art = _ingest(db_url, store_root, data=b"p", key="t/p", retention="staging", pinned=True)
    assert unpin_artifact(art.id, db_url=db_url) is True
    with sync_session(db_url) as session:
        row = session.scalar(select(Artifact).where(Artifact.id == art.id))
        assert row.pinned is False


def test_pin_unknown_returns_false(db_url: str, store_root: Path) -> None:
    assert pin_artifact("00000000-0000-0000-0000-000000000000", db_url=db_url) is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_store_stats(db_url: str, store_root: Path) -> None:
    _ingest(db_url, store_root, data=b"a" * 100, key="t/1", retention="staging")
    result = runner.invoke(
        app, ["store", "stats", "--store-root", str(store_root), "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "staging" in result.output


def test_cli_store_gc_dry_run(db_url: str, store_root: Path) -> None:
    _ingest(
        db_url,
        store_root,
        data=b"old" * 50,
        key="t/old",
        retention="staging",
        age_days=100,
    )
    result = runner.invoke(
        app,
        ["store", "gc", "--store-root", str(store_root), "--db-url", db_url, "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "would free" in result.output


def test_cli_store_gc_real(db_url: str, store_root: Path) -> None:
    art = _ingest(
        db_url,
        store_root,
        data=b"old" * 50,
        key="t/old",
        retention="staging",
        age_days=100,
    )
    result = runner.invoke(
        app, ["store", "gc", "--store-root", str(store_root), "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "freed" in result.output
    with sync_session(db_url) as session:
        assert session.scalar(select(Artifact).where(Artifact.id == art.id)) is None


def test_cli_store_pin_unpin(db_url: str, store_root: Path) -> None:
    art = _ingest(db_url, store_root, data=b"p", key="t/p", retention="staging")
    r1 = runner.invoke(app, ["store", "pin", art.id, "--db-url", db_url])
    assert r1.exit_code == 0
    assert "Pinned" in r1.output
    r2 = runner.invoke(app, ["store", "unpin", art.id, "--db-url", db_url])
    assert r2.exit_code == 0
    assert "Unpinned" in r2.output


def test_cli_store_pin_unknown(db_url: str, store_root: Path) -> None:
    result = runner.invoke(
        app, ["store", "pin", "00000000-0000-0000-0000-000000000000", "--db-url", db_url]
    )
    assert result.exit_code != 0
