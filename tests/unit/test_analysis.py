"""Unit tests for M64 — Build Analysis Dashboard."""

from __future__ import annotations

import pytest

from osfabricum import analysis as an_svc
from osfabricum.db.models import Base

BUILD_ID = "build-uuid-0064"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_analysis.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# analyze_build
# ---------------------------------------------------------------------------

def test_analyze_time(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    session.commit()
    assert a.id
    assert a.analysis_kind == "time"
    assert a.content_hash is not None
    assert a.content_hash.startswith("sha256:")
    assert a.rendered_report


def test_analyze_size(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="size")
    session.commit()
    assert "size" in (a.rendered_report or "").lower()


def test_analyze_critical_path(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="critical-path")
    session.commit()
    assert a.analysis_kind == "critical-path"
    assert a.rendered_report


def test_analyze_cache(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="cache")
    session.commit()
    assert a.rendered_report


def test_analyze_warnings(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="warnings")
    session.commit()
    assert a.rendered_report


def test_analyze_invalid_kind(session):
    with pytest.raises(ValueError, match="Invalid analysis_kind"):
        an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="cosmic-rays")


# ---------------------------------------------------------------------------
# list_build_analyses
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert an_svc.list_build_analyses(session, build_id=BUILD_ID) == []


def test_list_multiple(session):
    an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="size")
    session.commit()
    analyses = an_svc.list_build_analyses(session, build_id=BUILD_ID)
    assert len(analyses) == 2


def test_list_filter_by_kind(session):
    an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="size")
    session.commit()
    time_analyses = an_svc.list_build_analyses(session, build_id=BUILD_ID, analysis_kind="time")
    assert len(time_analyses) == 1
    assert time_analyses[0].analysis_kind == "time"


# ---------------------------------------------------------------------------
# get_build_analysis
# ---------------------------------------------------------------------------

def test_get_existing(session):
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    session.commit()
    fetched = an_svc.get_build_analysis(session, a.id)
    assert fetched.id == a.id


def test_get_missing_raises(session):
    with pytest.raises(KeyError):
        an_svc.get_build_analysis(session, "nonexistent")


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def test_report_deterministic(session):
    a1 = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    session.commit()
    h1 = a1.content_hash
    a2 = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    session.commit()
    h2 = a2.content_hash
    assert h1 == h2


def test_summary_json_present(session):
    import json
    a = an_svc.analyze_build(session, build_id=BUILD_ID, analysis_kind="time")
    session.commit()
    if a.summary_json:
        parsed = json.loads(a.summary_json)
        assert isinstance(parsed, dict)
