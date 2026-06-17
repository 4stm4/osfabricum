"""Unit tests for M61 — Attended Upgrade / Rebuild Service."""

from __future__ import annotations

import pytest

from osfabricum import upgrade as upg_svc
from osfabricum.db.models import Base

DIST_ID = "dist-uuid-0061"
PROFILE_ID = "prof-uuid-0061"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_upgrade.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# create_upgrade_request
# ---------------------------------------------------------------------------

def test_create_request_defaults(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    assert req.id
    assert req.status == "pending"
    assert req.target_channel == "stable"
    assert req.distribution_id == DIST_ID


def test_create_request_with_channel(session):
    req = upg_svc.create_upgrade_request(
        session, distribution_id=DIST_ID, target_channel="nightly", target_version="2.0.0"
    )
    session.commit()
    assert req.target_channel == "nightly"
    assert req.target_version == "2.0.0"


def test_create_request_no_dist(session):
    req = upg_svc.create_upgrade_request(session)
    session.commit()
    assert req.id
    assert req.distribution_id is None


# ---------------------------------------------------------------------------
# list_upgrade_requests
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert upg_svc.list_upgrade_requests(session) == []


def test_list_filter_by_dist(session):
    upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    upg_svc.create_upgrade_request(session, distribution_id="other-dist")
    session.commit()
    result = upg_svc.list_upgrade_requests(session, distribution_id=DIST_ID)
    assert len(result) == 1
    assert result[0].distribution_id == DIST_ID


def test_list_filter_by_status(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.update_upgrade_status(session, req.id, "running")
    session.commit()
    running = upg_svc.list_upgrade_requests(session, status="running")
    assert len(running) == 1
    pending = upg_svc.list_upgrade_requests(session, status="pending")
    assert pending == []


# ---------------------------------------------------------------------------
# get_upgrade_request
# ---------------------------------------------------------------------------

def test_get_existing(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    fetched = upg_svc.get_upgrade_request(session, req.id)
    assert fetched.id == req.id


def test_get_missing_raises(session):
    with pytest.raises(KeyError):
        upg_svc.get_upgrade_request(session, "nonexistent")


# ---------------------------------------------------------------------------
# update_upgrade_status
# ---------------------------------------------------------------------------

def test_update_status_to_running(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.update_upgrade_status(session, req.id, "running")
    session.commit()
    assert req.status == "running"
    assert req.completed_at is None


def test_update_status_terminal_sets_completed(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.update_upgrade_status(session, req.id, "success")
    session.commit()
    assert req.status == "success"
    assert req.completed_at is not None


def test_update_status_failed(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.update_upgrade_status(session, req.id, "failed")
    session.commit()
    assert req.status == "failed"
    assert req.completed_at is not None


# ---------------------------------------------------------------------------
# record_upgrade_result
# ---------------------------------------------------------------------------

def test_record_result(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    result = upg_svc.record_upgrade_result(
        session, upgrade_id=req.id, status="success",
        error_message=None,
    )
    session.commit()
    assert result.id
    assert result.upgrade_id == req.id
    assert result.status == "success"


def test_record_result_updates_request_status(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.record_upgrade_result(session, upgrade_id=req.id, status="failed", error_message="timeout")
    session.commit()
    assert req.status == "failed"


def test_list_upgrade_results(session):
    req = upg_svc.create_upgrade_request(session, distribution_id=DIST_ID)
    session.commit()
    upg_svc.record_upgrade_result(session, upgrade_id=req.id, status="success")
    session.commit()
    results = upg_svc.list_upgrade_results(session, req.id)
    assert len(results) == 1
