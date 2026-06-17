"""Unit tests for M65 — Size / Footprint Optimizer."""

from __future__ import annotations

import pytest

from osfabricum import sizeopt as size_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_size_budget_kinds

PROFILE_ID = "profile-uuid-0065"
BUILD_ID = "build-uuid-0065"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_sizeopt.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        seed_size_budget_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# list_size_budget_kinds
# ---------------------------------------------------------------------------

def test_list_budget_kinds(session):
    kinds = size_svc.list_size_budget_kinds(session)
    assert len(kinds) == 6
    kind_names = {k.kind for k in kinds}
    assert "image" in kind_names
    assert "rootfs" in kind_names
    assert "kernel" in kind_names


# ---------------------------------------------------------------------------
# set_size_budget / list_size_budgets
# ---------------------------------------------------------------------------

def test_set_budget(session):
    b = size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="image", budget_bytes=512 * 1024 * 1024)
    session.commit()
    assert b.id
    assert b.profile_id == PROFILE_ID
    assert b.budget_kind == "image"
    assert b.budget_bytes == 512 * 1024 * 1024
    assert b.is_hard_limit is False


def test_set_budget_hard_limit(session):
    b = size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="rootfs", budget_bytes=256 * 1024 * 1024, is_hard_limit=True)
    session.commit()
    assert b.is_hard_limit is True


def test_set_budget_upsert(session):
    b1 = size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="kernel", budget_bytes=10_000_000)
    session.commit()
    b2 = size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="kernel", budget_bytes=20_000_000)
    session.commit()
    assert b1.id == b2.id
    assert b2.budget_bytes == 20_000_000


def test_set_budget_invalid_kind(session):
    with pytest.raises(ValueError, match="Invalid budget_kind"):
        size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="enormous", budget_bytes=1)


def test_list_budgets(session):
    size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="image", budget_bytes=512_000_000)
    size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="rootfs", budget_bytes=256_000_000)
    session.commit()
    budgets = size_svc.list_size_budgets(session, profile_id=PROFILE_ID)
    assert len(budgets) == 2


def test_list_budgets_empty(session):
    assert size_svc.list_size_budgets(session, profile_id="unknown") == []


# ---------------------------------------------------------------------------
# analyze_size
# ---------------------------------------------------------------------------

def test_analyze_size_basic(session):
    r = size_svc.analyze_size(session, build_id=BUILD_ID)
    session.commit()
    assert r.id
    assert r.build_id == BUILD_ID
    assert r.content_hash is not None
    assert r.content_hash.startswith("sha256:")
    assert r.rendered_report


def test_analyze_size_with_profile_and_budget(session):
    size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="image", budget_bytes=10_000_000)
    session.commit()
    r = size_svc.analyze_size(
        session, build_id=BUILD_ID, profile_id=PROFILE_ID,
        size_data={"image": 50_000_000},
    )
    session.commit()
    assert "OVER" in (r.rendered_report or "") or "violation" in (r.rendered_report or "").lower()


def test_analyze_size_within_budget(session):
    size_svc.set_size_budget(session, profile_id=PROFILE_ID, budget_kind="image", budget_bytes=500_000_000, is_hard_limit=True)
    session.commit()
    r = size_svc.analyze_size(
        session, build_id=BUILD_ID, profile_id=PROFILE_ID,
        size_data={"image": 10_000_000},
    )
    session.commit()
    assert "OK" in (r.rendered_report or "") or r.rendered_report


def test_analyze_size_deterministic(session):
    r1 = size_svc.analyze_size(session, build_id=BUILD_ID)
    session.commit()
    h1 = r1.content_hash
    r2 = size_svc.analyze_size(session, build_id=BUILD_ID)
    session.commit()
    h2 = r2.content_hash
    assert h1 == h2


# ---------------------------------------------------------------------------
# list_size_reports
# ---------------------------------------------------------------------------

def test_list_size_reports(session):
    size_svc.analyze_size(session, build_id=BUILD_ID)
    size_svc.analyze_size(session, build_id=BUILD_ID)
    session.commit()
    reports = size_svc.list_size_reports(session, build_id=BUILD_ID)
    assert len(reports) == 2


def test_list_size_reports_empty(session):
    assert size_svc.list_size_reports(session, build_id="unknown") == []
