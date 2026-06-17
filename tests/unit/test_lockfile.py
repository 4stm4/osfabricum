"""Unit tests for M62 — Manifest / Lockfile System."""

from __future__ import annotations

import pytest

from osfabricum import lockfile as lf_svc
from osfabricum.db.models import Base

DIST_ID = "dist-uuid-0062"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_lockfile.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def lf(session):
    obj = lf_svc.create_lockfile(session, distribution_id=DIST_ID, lock_version="1")
    session.commit()
    return obj


# ---------------------------------------------------------------------------
# create_lockfile
# ---------------------------------------------------------------------------

def test_create_defaults(session):
    obj = lf_svc.create_lockfile(session, distribution_id=DIST_ID)
    session.commit()
    assert obj.id
    assert obj.lock_version == "1"
    assert obj.content_hash is None


def test_create_with_version(session):
    obj = lf_svc.create_lockfile(session, distribution_id=DIST_ID, lock_version="2024.01")
    session.commit()
    assert obj.lock_version == "2024.01"


# ---------------------------------------------------------------------------
# list_lockfiles
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert lf_svc.list_lockfiles(session) == []


def test_list_by_dist(session, lf):
    lf_svc.create_lockfile(session, distribution_id="other-dist")
    session.commit()
    result = lf_svc.list_lockfiles(session, distribution_id=DIST_ID)
    assert len(result) == 1
    assert result[0].distribution_id == DIST_ID


# ---------------------------------------------------------------------------
# get_lockfile
# ---------------------------------------------------------------------------

def test_get_existing(session, lf):
    fetched = lf_svc.get_lockfile(session, lf.id)
    assert fetched.id == lf.id


def test_get_missing_raises(session):
    with pytest.raises(KeyError):
        lf_svc.get_lockfile(session, "nonexistent")


# ---------------------------------------------------------------------------
# add_lockfile_entry
# ---------------------------------------------------------------------------

def test_add_entry(session, lf):
    entry = lf_svc.add_lockfile_entry(
        session, lockfile_id=lf.id,
        entry_kind="package", entry_key="busybox", version="1.36.1",
    )
    session.commit()
    assert entry.id
    assert entry.entry_kind == "package"
    assert entry.entry_key == "busybox"


def test_add_entry_upsert(session, lf):
    e1 = lf_svc.add_lockfile_entry(session, lf.id, "package", "bash", version="5.2")
    session.commit()
    e2 = lf_svc.add_lockfile_entry(session, lf.id, "package", "bash", version="5.3")
    session.commit()
    assert e1.id == e2.id
    assert e2.version == "5.3"


def test_add_entry_clears_hash(session, lf):
    lf_svc.render_lockfile(session, lf.id)
    session.commit()
    assert lf.content_hash is not None
    lf_svc.add_lockfile_entry(session, lf.id, "package", "gzip", version="1.13")
    session.commit()
    assert lf.content_hash is None


def test_add_entry_invalid_kind(session, lf):
    with pytest.raises(ValueError, match="Invalid entry_kind"):
        lf_svc.add_lockfile_entry(session, lf.id, "unknown", "foo")


# ---------------------------------------------------------------------------
# list_lockfile_entries
# ---------------------------------------------------------------------------

def test_list_entries(session, lf):
    lf_svc.add_lockfile_entry(session, lf.id, "package", "bash", "5.2")
    lf_svc.add_lockfile_entry(session, lf.id, "kernel", "linux", "6.6")
    session.commit()
    all_entries = lf_svc.list_lockfile_entries(session, lf.id)
    assert len(all_entries) == 2
    pkg_entries = lf_svc.list_lockfile_entries(session, lf.id, entry_kind="package")
    assert len(pkg_entries) == 1
    assert pkg_entries[0].entry_key == "bash"


# ---------------------------------------------------------------------------
# render_lockfile
# ---------------------------------------------------------------------------

def test_render_sets_hash(session, lf):
    lf_svc.add_lockfile_entry(session, lf.id, "package", "busybox", "1.36.1")
    session.commit()
    result = lf_svc.render_lockfile(session, lf.id)
    session.commit()
    assert result.content_hash is not None
    assert result.content_hash.startswith("sha256:")
    assert "busybox" in (result.rendered_lock or "")


def test_render_deterministic(session, lf):
    lf_svc.add_lockfile_entry(session, lf.id, "package", "busybox", "1.36.1")
    session.commit()
    h1 = lf_svc.render_lockfile(session, lf.id).content_hash
    session.commit()
    h2 = lf_svc.render_lockfile(session, lf.id).content_hash
    assert h1 == h2


def test_render_missing_raises(session):
    with pytest.raises(KeyError):
        lf_svc.render_lockfile(session, "nonexistent")


# ---------------------------------------------------------------------------
# diff_lockfiles
# ---------------------------------------------------------------------------

def test_diff_lockfiles(session):
    lf_a = lf_svc.create_lockfile(session, distribution_id=DIST_ID, lock_version="1")
    lf_b = lf_svc.create_lockfile(session, distribution_id=DIST_ID, lock_version="2")
    session.commit()
    lf_svc.add_lockfile_entry(session, lf_a.id, "package", "bash", "5.1")
    lf_svc.add_lockfile_entry(session, lf_a.id, "package", "busybox", "1.35")
    lf_svc.add_lockfile_entry(session, lf_b.id, "package", "bash", "5.2")
    lf_svc.add_lockfile_entry(session, lf_b.id, "package", "gzip", "1.13")
    session.commit()
    diff = lf_svc.diff_lockfiles(session, lf_a.id, lf_b.id)
    changed_keys = {e["key"] if isinstance(e, dict) else e for e in diff["changed"]}
    removed_keys = {e["key"] if isinstance(e, dict) else e for e in diff["removed"]}
    added_keys = {e["key"] if isinstance(e, dict) else e for e in diff["added"]}
    assert "bash" in changed_keys
    assert "busybox" in removed_keys
    assert "gzip" in added_keys
