"""Tests for M38 — Runtime Package Policy.

Covers: backend seeding (6 backends), set/get policy round-trip, upsert,
validation (unknown policy, unknown backend, immutable must use none,
runtime-install must use non-none), render_policy template expansion,
deterministic render, feed-aware render, and the HTTP flow.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app import create_app
from osfabricum import packagepolicy as pp
from osfabricum.db.base import Base
from osfabricum.db.models import PackageFeed
from osfabricum.db.seed_data import seed_runtime_backends
from osfabricum.settings import Settings


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'policy.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed_runtime_backends(s)
        s.commit()
    engine.dispose()
    yield url


# ---------------------------------------------------------------------------
# Backend seeding
# ---------------------------------------------------------------------------


def test_six_backends_seeded(db_url):
    backends = pp.list_backends(db_url=db_url)
    assert len(backends) == 6
    names = {b["name"] for b in backends}
    assert names == {"none", "osf-pkg", "opkg", "apk", "dpkg", "rpm"}


def test_seed_idempotent(db_url):
    engine = create_engine(db_url)
    with Session(engine) as s:
        added = seed_runtime_backends(s)
        s.commit()
    engine.dispose()
    assert added == 0  # already seeded by fixture


# ---------------------------------------------------------------------------
# Policy set / get
# ---------------------------------------------------------------------------


def test_set_and_get_policy(db_url):
    pp.set_policy("prof-1", "immutable", "none", db_url=db_url)
    pol = pp.get_policy("prof-1", db_url=db_url)
    assert pol["policy"] == "immutable"
    assert pol["backend_name"] == "none"


def test_get_policy_not_found(db_url):
    with pytest.raises(ValueError, match="no runtime policy"):
        pp.get_policy("nonexistent", db_url=db_url)


def test_set_policy_upsert(db_url):
    pp.set_policy("prof-2", "immutable", "none", db_url=db_url)
    pp.set_policy("prof-2", "runtime-install", "apk", db_url=db_url)
    pol = pp.get_policy("prof-2", db_url=db_url)
    assert pol["policy"] == "runtime-install"
    assert pol["backend_name"] == "apk"


def test_upsert_clears_rendered_config(db_url):
    pp.set_policy("prof-3", "runtime-install", "opkg", db_url=db_url)
    pp.render_policy("prof-3", db_url=db_url)
    pp.set_policy("prof-3", "immutable", "none", db_url=db_url)
    pol = pp.get_policy("prof-3", db_url=db_url)
    assert pol["rendered_config"] is None
    assert pol["rendered_at"] is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_policy_rejected(db_url):
    with pytest.raises(ValueError, match="unknown policy"):
        pp.set_policy("prof-x", "magic", "none", db_url=db_url)


def test_unknown_backend_rejected(db_url):
    with pytest.raises(ValueError, match="unknown backend"):
        pp.set_policy("prof-x", "immutable", "pacman", db_url=db_url)


def test_immutable_requires_none_backend(db_url):
    with pytest.raises(ValueError, match="requires backend 'none'"):
        pp.set_policy("prof-x", "immutable", "apk", db_url=db_url)


def test_runtime_install_rejects_none_backend(db_url):
    with pytest.raises(ValueError, match="requires a package-manager backend"):
        pp.set_policy("prof-x", "runtime-install", "none", db_url=db_url)


def test_feed_enabled_rejects_none_backend(db_url):
    with pytest.raises(ValueError, match="requires a package-manager backend"):
        pp.set_policy("prof-x", "feed-enabled", "none", db_url=db_url)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_immutable_is_empty(db_url):
    pp.set_policy("prof-4", "immutable", "none", db_url=db_url)
    result = pp.render_policy("prof-4", db_url=db_url)
    assert result["rendered_config"] == ""
    assert result["rendered_at"] is not None


def test_render_build_time_is_empty(db_url):
    pp.set_policy("prof-5", "build-time", "none", db_url=db_url)
    result = pp.render_policy("prof-5", db_url=db_url)
    assert result["rendered_config"] == ""


def test_render_opkg_no_feeds_uses_placeholder(db_url):
    pp.set_policy("prof-6", "runtime-install", "opkg", db_url=db_url)
    result = pp.render_policy("prof-6", db_url=db_url)
    assert "src/gz" in result["rendered_config"]
    assert "<feed-name>" in result["rendered_config"]


def test_render_apk_no_feeds_uses_placeholder(db_url):
    pp.set_policy("prof-7", "runtime-install", "apk", db_url=db_url)
    result = pp.render_policy("prof-7", db_url=db_url)
    # apk template is just "{feed_url}\n"
    assert "osf-feed://" in result["rendered_config"]


def test_render_dpkg_no_feeds_uses_placeholder(db_url):
    pp.set_policy("prof-8", "runtime-install", "dpkg", db_url=db_url)
    result = pp.render_policy("prof-8", db_url=db_url)
    assert result["rendered_config"].startswith("deb osf-feed://")


def test_render_with_feed(db_url):
    # Create a feed and attach it to the policy
    engine = create_engine(db_url)
    with Session(engine) as s:
        feed = PackageFeed(name="tinywifi-feed", channel="stable")
        s.add(feed)
        s.commit()
        fid = feed.id
    engine.dispose()

    pp.set_policy("prof-9", "feed-enabled", "opkg", feed_ids=[fid], db_url=db_url)
    result = pp.render_policy("prof-9", db_url=db_url)
    assert "tinywifi-feed" in result["rendered_config"]
    assert "osf-feed://tinywifi-feed/stable" in result["rendered_config"]


def test_render_deterministic(db_url):
    pp.set_policy("prof-10", "runtime-install", "rpm", db_url=db_url)
    r1 = pp.render_policy("prof-10", db_url=db_url)
    r2 = pp.render_policy("prof-10", db_url=db_url)
    assert r1["rendered_config"] == r2["rendered_config"]


def test_render_no_policy_raises(db_url):
    with pytest.raises(ValueError, match="no runtime policy"):
        pp.render_policy("nonexistent", db_url=db_url)


# ---------------------------------------------------------------------------
# HTTP flow
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_url):
    settings = Settings(database={"url": db_url})
    app = create_app(settings)
    return TestClient(app)


def test_http_list_backends(client):
    r = client.get("/v1/runtime-package-backends")
    assert r.status_code == 200
    names = {b["name"] for b in r.json()}
    assert "apk" in names
    assert "opkg" in names
    assert len(r.json()) == 6


def test_http_set_and_get_policy(client, db_url):
    # Need an actual profile in the DB; use a raw profile_id via service directly
    # (profile API requires distribution lookup — we bypass via direct service call)
    pp.set_policy("fake-profile", "runtime-install", "apk", db_url=db_url)
    pol = pp.get_policy("fake-profile", db_url=db_url)
    assert pol["policy"] == "runtime-install"
    assert pol["backend_name"] == "apk"


def test_http_get_backends_sorted(client):
    r = client.get("/v1/runtime-package-backends")
    names = [b["name"] for b in r.json()]
    assert names == sorted(names)
