"""Tests for M37 — Package Feed / Repository Publisher.

Covers: create/list feeds, add index entries, scope a feed by distribution/arch/
libc/kernel_release, publish (deterministic index hash + FeedSignature record),
idempotent re-publish, FeedPublishJob status, and the HTTP flow.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app import create_app
from osfabricum import packageworkspace as pw
from osfabricum.db.base import Base
from osfabricum.db.models import FeedPublishJob, PackageFeedIndex
from osfabricum.settings import Settings


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'fp.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url


@pytest.fixture
def feed_id(db_url) -> str:
    f = pw.create_feed("test-feed", channel="stable", db_url=db_url)
    return f["id"]


# ---------------------------------------------------------------------------
# Feed CRUD
# ---------------------------------------------------------------------------


def test_create_and_list_feed(db_url):
    pw.create_feed("main-feed", channel="stable", description="primary", db_url=db_url)
    pw.create_feed("edge-feed", channel="edge", db_url=db_url)
    feeds = pw.list_feeds(db_url=db_url)
    names = [f["name"] for f in feeds]
    assert "main-feed" in names
    assert "edge-feed" in names


def test_duplicate_feed_rejected(db_url, feed_id):
    with pytest.raises(ValueError, match="already exists"):
        pw.create_feed("test-feed", db_url=db_url)


def test_get_feed_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        pw.get_feed("nonexistent", db_url=db_url)


# ---------------------------------------------------------------------------
# Index entries
# ---------------------------------------------------------------------------


def test_add_index_entries(db_url, feed_id):
    pw.add_feed_index(feed_id, "busybox", "1.36.1", cache_key="pkgcache:aaa", db_url=db_url)
    pw.add_feed_index(feed_id, "musl", "1.2.5", cache_key="pkgcache:bbb", db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    names = [e["package_name"] for e in f["entries"]]
    assert "busybox" in names
    assert "musl" in names
    assert len(f["entries"]) == 2


def test_entries_ordered_by_position(db_url, feed_id):
    pw.add_feed_index(feed_id, "alpha", "1.0", db_url=db_url)
    pw.add_feed_index(feed_id, "beta", "2.0", db_url=db_url)
    pw.add_feed_index(feed_id, "gamma", "3.0", db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    positions = [e["position"] for e in f["entries"]]
    assert positions == sorted(positions)


def test_add_index_unknown_feed(db_url):
    with pytest.raises(ValueError, match="not found"):
        pw.add_feed_index("bad-id", "pkg", "1.0", db_url=db_url)


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


def test_scope_feed(db_url, feed_id):
    pw.scope_feed(feed_id, distribution="netos", arch="x86_64", db_url=db_url)
    pw.scope_feed(feed_id, arch="arm64", libc="musl", db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    assert len(f["channels"]) == 2
    dists = {c["distribution"] for c in f["channels"]}
    assert "netos" in dists


def test_scope_kernel_release(db_url, feed_id):
    pw.scope_feed(feed_id, kernel_release="6.6.30", arch="arm", db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    kr = [c["kernel_release"] for c in f["channels"]]
    assert "6.6.30" in kr


def test_scope_unknown_feed(db_url):
    with pytest.raises(ValueError, match="not found"):
        pw.scope_feed("bad-id", arch="x86_64", db_url=db_url)


# ---------------------------------------------------------------------------
# Publish (sign)
# ---------------------------------------------------------------------------


def test_publish_empty_feed(db_url, feed_id):
    result = pw.publish_feed(feed_id, db_url=db_url)
    assert result["status"] == "done"
    assert result["entry_count"] == 0
    assert result["index_hash"].startswith("sha256:")


def test_publish_stores_signature(db_url, feed_id):
    pw.add_feed_index(feed_id, "busybox", "1.36.1", db_url=db_url)
    pw.publish_feed(feed_id, db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    assert f["last_signature"] is not None
    assert f["last_signature"]["entry_count"] == 1
    assert f["last_signature"]["algorithm"] == "sha256"


def test_publish_hash_is_deterministic(db_url, feed_id):
    pw.add_feed_index(feed_id, "busybox", "1.36.1", cache_key="pkgcache:aaa", db_url=db_url)
    r1 = pw.publish_feed(feed_id, db_url=db_url)
    r2 = pw.publish_feed(feed_id, db_url=db_url)
    assert r1["index_hash"] == r2["index_hash"]


def test_publish_hash_matches_manual_sha256(db_url, feed_id):
    pw.add_feed_index(feed_id, "musl", "1.2.5", cache_key="pkgcache:ccc", db_url=db_url)

    engine = create_engine(db_url)
    with Session(engine) as s:
        entries = (
            s.query(PackageFeedIndex)
            .filter_by(feed_id=feed_id)
            .order_by(PackageFeedIndex.position)
            .all()
        )
        payload = [
            {
                "package_name": e.package_name,
                "version": e.version,
                "cache_key": e.cache_key,
                "position": e.position,
            }
            for e in entries
        ]
    engine.dispose()

    expected = "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    result = pw.publish_feed(feed_id, db_url=db_url)
    assert result["index_hash"] == expected


def test_publish_hash_changes_after_new_entry(db_url, feed_id):
    pw.add_feed_index(feed_id, "busybox", "1.36.1", db_url=db_url)
    r1 = pw.publish_feed(feed_id, db_url=db_url)
    pw.add_feed_index(feed_id, "musl", "1.2.5", db_url=db_url)
    r2 = pw.publish_feed(feed_id, db_url=db_url)
    assert r1["index_hash"] != r2["index_hash"]
    assert r2["entry_count"] == 2


def test_publish_job_recorded(db_url, feed_id):
    pw.publish_feed(feed_id, db_url=db_url)
    engine = create_engine(db_url)
    with Session(engine) as s:
        jobs = s.query(FeedPublishJob).filter_by(feed_id=feed_id).all()
    engine.dispose()
    assert len(jobs) >= 1
    assert jobs[0].status == "done"
    assert jobs[0].completed_at is not None


def test_publish_unknown_feed(db_url):
    with pytest.raises(ValueError, match="not found"):
        pw.publish_feed("bad-id", db_url=db_url)


# ---------------------------------------------------------------------------
# Multiple signatures — get_feed returns latest
# ---------------------------------------------------------------------------


def test_get_feed_returns_latest_signature(db_url, feed_id):
    r1 = pw.publish_feed(feed_id, db_url=db_url)
    pw.add_feed_index(feed_id, "curl", "8.7.1", db_url=db_url)
    r2 = pw.publish_feed(feed_id, db_url=db_url)
    f = pw.get_feed(feed_id, db_url=db_url)
    assert f["last_signature"]["index_hash"] == r2["index_hash"]
    assert f["last_signature"]["index_hash"] != r1["index_hash"]


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def test_promote_package(db_url):
    result = pw.promote("busybox", "1.36.1", "stable", from_channel="staging", db_url=db_url)
    assert result["package_name"] == "busybox"
    assert result["to_channel"] == "stable"


# ---------------------------------------------------------------------------
# HTTP flow
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_url):
    settings = Settings(database={"url": db_url})
    app = create_app(settings)
    return TestClient(app)


def test_http_create_and_publish_feed(client):
    r = client.post("/v1/package-feeds", json={"name": "ci-feed", "channel": "edge"})
    assert r.status_code == 201
    fid = r.json()["id"]

    client.post(
        f"/v1/package-feeds/{fid}/index",
        json={"package_name": "busybox", "version": "1.36.1"},
    )

    r = client.post(f"/v1/package-feeds/{fid}/publish")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "done"
    assert body["entry_count"] == 1
    assert body["index_hash"].startswith("sha256:")


def test_http_get_feed(client):
    fid = client.post(
        "/v1/package-feeds", json={"name": "show-feed", "channel": "stable"}
    ).json()["id"]
    client.post(
        f"/v1/package-feeds/{fid}/index",
        json={"package_name": "musl", "version": "1.2.5", "cache_key": "pkgcache:xyz"},
    )
    client.post(f"/v1/package-feeds/{fid}/scope", json={"arch": "arm64", "libc": "musl"})
    client.post(f"/v1/package-feeds/{fid}/publish")

    r = client.get(f"/v1/package-feeds/{fid}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "show-feed"
    assert len(body["entries"]) == 1
    assert len(body["channels"]) == 1
    assert body["last_signature"] is not None


def test_http_get_feed_not_found(client):
    r = client.get("/v1/package-feeds/nonexistent")
    assert r.status_code == 404


def test_http_scope_feed(client):
    fid = client.post(
        "/v1/package-feeds", json={"name": "scoped-feed", "channel": "lts"}
    ).json()["id"]
    r = client.post(
        f"/v1/package-feeds/{fid}/scope",
        json={"distribution": "tinywifi", "arch": "armv6", "kernel_release": "6.1.90"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["distribution"] == "tinywifi"
    assert body["kernel_release"] == "6.1.90"
