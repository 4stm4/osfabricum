"""Unit tests for M69 — Public Artifact Repository / Release Publishing."""

from __future__ import annotations

import pytest

from osfabricum import repository as repo_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_release_channels

DIST_ID = "dist-uuid-0069"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_repository.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        seed_release_channels(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def repo(session):
    r = repo_svc.create_repository(session, name="main-repo", repo_kind="image")
    session.commit()
    return r


@pytest.fixture()
def release(session):
    r = repo_svc.create_release(session, channel="stable", version="1.0.0", distribution_id=DIST_ID)
    session.commit()
    return r


# ---------------------------------------------------------------------------
# list_release_channels
# ---------------------------------------------------------------------------

def test_list_channels(session):
    channels = repo_svc.list_release_channels(session)
    assert len(channels) == 5
    names = {c.channel for c in channels}
    assert "stable" in names
    assert "nightly" in names
    assert "lts" in names


# ---------------------------------------------------------------------------
# create_repository
# ---------------------------------------------------------------------------

def test_create_repo(session):
    r = repo_svc.create_repository(session, name="pkg-repo", repo_kind="package")
    session.commit()
    assert r.id
    assert r.name == "pkg-repo"
    assert r.repo_kind == "package"
    assert r.is_published is False


def test_create_repo_invalid_kind(session):
    with pytest.raises(ValueError, match="Invalid repo_kind"):
        repo_svc.create_repository(session, name="bad", repo_kind="git")


# ---------------------------------------------------------------------------
# list_repositories
# ---------------------------------------------------------------------------

def test_list_repos_empty(session):
    assert repo_svc.list_repositories(session) == []


def test_list_repos(session, repo):
    repo_svc.create_repository(session, name="fw-repo", repo_kind="firmware")
    session.commit()
    all_repos = repo_svc.list_repositories(session)
    assert len(all_repos) == 2


def test_list_repos_filter_by_kind(session, repo):
    repo_svc.create_repository(session, name="fw-repo", repo_kind="firmware")
    session.commit()
    image_repos = repo_svc.list_repositories(session, repo_kind="image")
    assert len(image_repos) == 1
    assert image_repos[0].repo_kind == "image"


# ---------------------------------------------------------------------------
# get_repository
# ---------------------------------------------------------------------------

def test_get_repo(session, repo):
    fetched = repo_svc.get_repository(session, repo.id)
    assert fetched.id == repo.id


def test_get_repo_missing(session):
    with pytest.raises(KeyError):
        repo_svc.get_repository(session, "nonexistent")


# ---------------------------------------------------------------------------
# create_release
# ---------------------------------------------------------------------------

def test_create_release(session):
    r = repo_svc.create_release(session, channel="stable", version="2.0.0")
    session.commit()
    assert r.id
    assert r.channel == "stable"
    assert r.version == "2.0.0"
    assert r.status == "draft"


def test_create_release_with_dist(session):
    r = repo_svc.create_release(session, channel="testing", version="2.1.0-beta", distribution_id=DIST_ID)
    session.commit()
    assert r.distribution_id == DIST_ID


# ---------------------------------------------------------------------------
# list_releases
# ---------------------------------------------------------------------------

def test_list_releases_empty(session):
    assert repo_svc.list_releases(session) == []


def test_list_releases_filter_channel(session):
    repo_svc.create_release(session, channel="stable", version="1.0.0")
    repo_svc.create_release(session, channel="nightly", version="20240101")
    session.commit()
    stable = repo_svc.list_releases(session, channel="stable")
    assert len(stable) == 1
    assert stable[0].channel == "stable"


def test_list_releases_filter_status(session):
    r = repo_svc.create_release(session, channel="stable", version="1.0.0")
    session.commit()
    repo_svc.promote_release(session, r.id, "published")
    session.commit()
    published = repo_svc.list_releases(session, status="published")
    assert len(published) == 1
    draft = repo_svc.list_releases(session, status="draft")
    assert len(draft) == 0


# ---------------------------------------------------------------------------
# get_release
# ---------------------------------------------------------------------------

def test_get_release(session, release):
    fetched = repo_svc.get_release(session, release.id)
    assert fetched.id == release.id


def test_get_release_missing(session):
    with pytest.raises(KeyError):
        repo_svc.get_release(session, "nonexistent")


# ---------------------------------------------------------------------------
# promote_release
# ---------------------------------------------------------------------------

def test_promote_to_published(session, release):
    r = repo_svc.promote_release(session, release.id, "published")
    session.commit()
    assert r.status == "published"


def test_promote_to_withdrawn(session, release):
    r = repo_svc.promote_release(session, release.id, "withdrawn")
    session.commit()
    assert r.status == "withdrawn"


def test_promote_invalid_status(session, release):
    with pytest.raises(ValueError, match="Invalid status"):
        repo_svc.promote_release(session, release.id, "superseded")


def test_promote_missing(session):
    with pytest.raises(KeyError):
        repo_svc.promote_release(session, "nonexistent", "published")


# ---------------------------------------------------------------------------
# add_release_artifact
# ---------------------------------------------------------------------------

def test_add_artifact(session, release):
    a = repo_svc.add_release_artifact(
        session, release.id,
        artifact_role="image", artifact_uri="s3://bucket/image.img",
    )
    session.commit()
    assert a.id
    assert a.artifact_role == "image"
    assert a.artifact_uri == "s3://bucket/image.img"


def test_add_artifact_upsert(session, release):
    a1 = repo_svc.add_release_artifact(session, release.id, "image", artifact_uri="s3://v1.img")
    session.commit()
    a2 = repo_svc.add_release_artifact(session, release.id, "image", artifact_uri="s3://v2.img")
    session.commit()
    assert a1.id == a2.id
    assert a2.artifact_uri == "s3://v2.img"


def test_add_artifact_invalid_role(session, release):
    with pytest.raises(ValueError, match="Invalid artifact_role"):
        repo_svc.add_release_artifact(session, release.id, "iso", artifact_uri="x")


# ---------------------------------------------------------------------------
# render_release_manifest
# ---------------------------------------------------------------------------

def test_render_manifest(session, release):
    repo_svc.add_release_artifact(session, release.id, "image", artifact_uri="s3://img.bin")
    session.commit()
    r = repo_svc.render_release_manifest(session, release.id)
    session.commit()
    assert r.content_hash is not None
    assert r.content_hash.startswith("sha256:")
    assert "stable" in (r.rendered_release_manifest or "")
    assert "1.0.0" in (r.rendered_release_manifest or "")


def test_render_manifest_deterministic(session, release):
    h1 = repo_svc.render_release_manifest(session, release.id).content_hash
    session.commit()
    h2 = repo_svc.render_release_manifest(session, release.id).content_hash
    assert h1 == h2


def test_render_manifest_missing(session):
    with pytest.raises(KeyError):
        repo_svc.render_release_manifest(session, "nonexistent")


# ---------------------------------------------------------------------------
# index_repository
# ---------------------------------------------------------------------------

def test_index_repository(session, repo, release):
    repo_svc.promote_release(session, release.id, "published")
    session.commit()
    idx = repo_svc.index_repository(session, repo.id, channel="stable")
    session.commit()
    assert idx.id
    assert idx.repository_id == repo.id
    assert idx.channel == "stable"
    assert idx.content_hash is not None
