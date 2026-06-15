"""Unit tests for M59 — Build / Profile / Release Diff."""

from __future__ import annotations

import json

import pytest

from osfabricum import diff as diff_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_diff_report_kinds


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_diff.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_diff_report_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def report(session):
    r = diff_svc.create_diff_report(
        session, entity_kind="profile",
        entity_a_id="profile-a", entity_b_id="profile-b",
    )
    session.commit()
    return r


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------


def test_diff_kinds_seeded(session):
    kinds = diff_svc.list_diff_report_kinds(session)
    assert len(kinds) == 7


def test_diff_kinds_ordered(session):
    kinds = diff_svc.list_diff_report_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_diff_kinds_valid_set(session):
    kinds = diff_svc.list_diff_report_kinds(session)
    assert {k.kind for k in kinds} == diff_svc.VALID_DIFF_KINDS


# ---------------------------------------------------------------------------
# create_diff_report
# ---------------------------------------------------------------------------


def test_create_report_basic(session, report):
    assert report.id is not None
    assert report.entity_kind == "profile"
    assert report.entity_a_id == "profile-a"
    assert report.entity_b_id == "profile-b"
    assert report.content_hash is None


def test_create_report_invalid_entity_kind(session):
    with pytest.raises(ValueError, match="Invalid entity_kind"):
        diff_svc.create_diff_report(session, "bad-kind", "a", "b")


def test_create_report_invalid_diff_kind(session):
    with pytest.raises(ValueError, match="Invalid diff_kind"):
        diff_svc.create_diff_report(session, "profile", "a", "b", diff_kind="bad")


def test_create_report_all_entity_kinds(session):
    for ek in sorted(diff_svc.VALID_ENTITY_KINDS):
        r = diff_svc.create_diff_report(session, ek, "x", "y")
        assert r.entity_kind == ek


def test_create_report_all_diff_kinds(session):
    for dk in sorted(diff_svc.VALID_DIFF_KINDS):
        r = diff_svc.create_diff_report(session, "build", "a", "b", diff_kind=dk)
        assert r.id is not None


# ---------------------------------------------------------------------------
# get / list
# ---------------------------------------------------------------------------


def test_get_report(session, report):
    fetched = diff_svc.get_diff_report(session, report.id)
    assert fetched.id == report.id


def test_get_report_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        diff_svc.get_diff_report(session, "nonexistent")


def test_list_reports_empty(session):
    assert diff_svc.list_diff_reports(session) == []


def test_list_reports_after_create(session, report):
    reports = diff_svc.list_diff_reports(session)
    assert len(reports) == 1


def test_list_reports_filter_by_entity_kind(session):
    diff_svc.create_diff_report(session, "profile", "a", "b")
    diff_svc.create_diff_report(session, "build", "c", "d")
    builds = diff_svc.list_diff_reports(session, entity_kind="build")
    assert len(builds) == 1 and builds[0].entity_kind == "build"


def test_list_reports_filter_by_entity_a(session):
    diff_svc.create_diff_report(session, "release", "r1", "r2")
    diff_svc.create_diff_report(session, "release", "r3", "r4")
    filtered = diff_svc.list_diff_reports(session, entity_a_id="r1")
    assert len(filtered) == 1 and filtered[0].entity_a_id == "r1"


def test_list_reports_filter_by_entity_b(session):
    diff_svc.create_diff_report(session, "build", "a", "b1")
    diff_svc.create_diff_report(session, "build", "a", "b2")
    filtered = diff_svc.list_diff_reports(session, entity_b_id="b2")
    assert len(filtered) == 1


# ---------------------------------------------------------------------------
# render_diff_report
# ---------------------------------------------------------------------------


def test_render_empty_data(session, report):
    r = diff_svc.render_diff_report(session, report.id)
    assert r.rendered_diff is not None
    assert r.content_hash is not None
    assert r.content_hash.startswith("sha256:")


def test_render_empty_shows_zero_counts(session, report):
    r = diff_svc.render_diff_report(session, report.id)
    assert "added   = 0" in r.rendered_diff
    assert "removed = 0" in r.rendered_diff
    assert "changed = 0" in r.rendered_diff


def test_render_detects_added(session, report):
    r = diff_svc.render_diff_report(session, report.id,
                                     a_data={}, b_data={"glibc": "2.36"})
    assert "glibc" in r.rendered_diff
    assert "[added]" in r.rendered_diff
    summary = json.loads(r.summary_json)
    assert summary["added"] == 1


def test_render_detects_removed(session, report):
    r = diff_svc.render_diff_report(session, report.id,
                                     a_data={"bash": "5.2"}, b_data={})
    assert "[removed]" in r.rendered_diff
    summary = json.loads(r.summary_json)
    assert summary["removed"] == 1


def test_render_detects_changed(session, report):
    r = diff_svc.render_diff_report(session, report.id,
                                     a_data={"glibc": "2.35"},
                                     b_data={"glibc": "2.36"})
    assert "[changed]" in r.rendered_diff
    summary = json.loads(r.summary_json)
    assert summary["changed"] == 1


def test_render_mixed_changes(session, report):
    a = {"glibc": "2.35", "bash": "5.1", "old-pkg": "1.0"}
    b = {"glibc": "2.36", "bash": "5.1", "new-pkg": "1.0"}
    r = diff_svc.render_diff_report(session, report.id, a_data=a, b_data=b)
    summary = json.loads(r.summary_json)
    assert summary["added"] == 1
    assert summary["removed"] == 1
    assert summary["changed"] == 1


def test_render_not_found_raises(session):
    with pytest.raises(KeyError, match="not found"):
        diff_svc.render_diff_report(session, "no-such-id")


def test_render_sets_summary_json(session, report):
    r = diff_svc.render_diff_report(session, report.id, a_data={"x": "1"}, b_data={})
    assert json.loads(r.summary_json)["removed"] == 1


def test_render_header_contains_entity_ids(session, report):
    r = diff_svc.render_diff_report(session, report.id)
    assert "profile-a" in r.rendered_diff
    assert "profile-b" in r.rendered_diff


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_render_same_data_same_hash(session):
    r1 = diff_svc.create_diff_report(session, "build", "a", "b")
    r2 = diff_svc.create_diff_report(session, "build", "a", "b")
    data = {"glibc": "2.36", "bash": "5.2"}
    diff_svc.render_diff_report(session, r1.id, a_data=data, b_data=data)
    diff_svc.render_diff_report(session, r2.id, a_data=data, b_data=data)
    session.refresh(r1)
    session.refresh(r2)
    assert r1.content_hash == r2.content_hash
