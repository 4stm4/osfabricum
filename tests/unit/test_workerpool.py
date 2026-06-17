"""Unit tests for M67 — Distributed Build Farm / Worker Pools."""

from __future__ import annotations

import pytest

from osfabricum import workerpool as wp_svc
from osfabricum.db.models import Base


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_workerpool.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def pool(session):
    p = wp_svc.create_worker_pool(session, name="main-pool", pool_kind="local", max_parallelism=4)
    session.commit()
    return p


# ---------------------------------------------------------------------------
# create_worker_pool
# ---------------------------------------------------------------------------

def test_create_pool(session):
    p = wp_svc.create_worker_pool(session, name="test-pool", pool_kind="local")
    session.commit()
    assert p.id
    assert p.name == "test-pool"
    assert p.pool_kind == "local"


def test_create_pool_invalid_kind(session):
    with pytest.raises(ValueError, match="Invalid pool_kind"):
        wp_svc.create_worker_pool(session, name="bad-pool", pool_kind="kubernetes")


# ---------------------------------------------------------------------------
# list_worker_pools
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert wp_svc.list_worker_pools(session) == []


def test_list_pools(session, pool):
    wp_svc.create_worker_pool(session, name="remote-pool", pool_kind="remote")
    session.commit()
    all_pools = wp_svc.list_worker_pools(session)
    assert len(all_pools) == 2


def test_list_pools_filter_by_kind(session, pool):
    wp_svc.create_worker_pool(session, name="remote-pool", pool_kind="remote")
    session.commit()
    local = wp_svc.list_worker_pools(session, pool_kind="local")
    assert len(local) == 1
    assert local[0].pool_kind == "local"


# ---------------------------------------------------------------------------
# get_worker_pool
# ---------------------------------------------------------------------------

def test_get_pool(session, pool):
    fetched = wp_svc.get_worker_pool(session, pool.id)
    assert fetched.id == pool.id


def test_get_pool_missing(session):
    with pytest.raises(KeyError):
        wp_svc.get_worker_pool(session, "nonexistent")


# ---------------------------------------------------------------------------
# update_worker_pool
# ---------------------------------------------------------------------------

def test_update_pool(session, pool):
    updated = wp_svc.update_worker_pool(session, pool.id, label="Updated", max_parallelism=8)
    session.commit()
    assert updated.label == "Updated"
    assert updated.max_parallelism == 8


def test_update_pool_invalid_kind(session, pool):
    with pytest.raises(ValueError):
        wp_svc.update_worker_pool(session, pool.id, pool_kind="kubernetes")


# ---------------------------------------------------------------------------
# add_pool_member
# ---------------------------------------------------------------------------

def test_add_member(session, pool):
    m = wp_svc.add_pool_member(session, pool_id=pool.id, worker_id="worker-001")
    session.commit()
    assert m.id
    assert m.worker_pool_id == pool.id
    assert m.worker_id == "worker-001"


def test_add_member_no_worker(session, pool):
    m = wp_svc.add_pool_member(session, pool_id=pool.id)
    session.commit()
    assert m.worker_id is None


def test_list_pool_members(session, pool):
    wp_svc.add_pool_member(session, pool.id, "w-1")
    wp_svc.add_pool_member(session, pool.id, "w-2")
    session.commit()
    members = wp_svc.list_pool_members(session, pool.id)
    assert len(members) == 2


# ---------------------------------------------------------------------------
# add_job_affinity
# ---------------------------------------------------------------------------

def test_add_affinity(session, pool):
    a = wp_svc.add_job_affinity(session, pool.id, job_kind="build", weight=10)
    session.commit()
    assert a.job_kind == "build"
    assert a.affinity_weight == 10


def test_list_affinities(session, pool):
    wp_svc.add_job_affinity(session, pool.id, "build", 10)
    wp_svc.add_job_affinity(session, pool.id, "sign", 5)
    session.commit()
    affinities = wp_svc.list_job_affinities(session, pool.id)
    assert len(affinities) == 2


# ---------------------------------------------------------------------------
# set_pool_quota
# ---------------------------------------------------------------------------

def test_set_quota(session, pool):
    q = wp_svc.set_pool_quota(session, pool.id, resource_kind="cpu", limit_value=8)
    session.commit()
    assert q.resource_kind == "cpu"
    assert q.limit_value == 8


def test_set_quota_upsert(session, pool):
    q1 = wp_svc.set_pool_quota(session, pool.id, resource_kind="memory", limit_value=8192)
    session.commit()
    q2 = wp_svc.set_pool_quota(session, pool.id, resource_kind="memory", limit_value=16384)
    session.commit()
    assert q1.id == q2.id
    assert q2.limit_value == 16384


def test_set_quota_invalid_resource(session, pool):
    with pytest.raises(ValueError, match="Invalid resource_kind"):
        wp_svc.set_pool_quota(session, pool.id, resource_kind="gpu", limit_value=4)


def test_list_quotas(session, pool):
    wp_svc.set_pool_quota(session, pool.id, "cpu", 8)
    wp_svc.set_pool_quota(session, pool.id, "memory", 16384)
    session.commit()
    quotas = wp_svc.list_pool_quotas(session, pool.id)
    assert len(quotas) == 2
