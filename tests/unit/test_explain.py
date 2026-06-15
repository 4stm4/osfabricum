"""Unit tests for M58 — Explain / Why Engine."""

from __future__ import annotations

import pytest

from osfabricum import explain as explain_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_explain_trace_kinds


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_explain.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_explain_trace_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Trace kinds
# ---------------------------------------------------------------------------


def test_trace_kinds_seeded(session):
    kinds = explain_svc.list_explain_trace_kinds(session)
    assert len(kinds) == 7


def test_trace_kinds_ordered(session):
    kinds = explain_svc.list_explain_trace_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_trace_kinds_have_label(session):
    kinds = explain_svc.list_explain_trace_kinds(session)
    assert all(k.label for k in kinds)


def test_trace_kinds_known_set(session):
    kinds = explain_svc.list_explain_trace_kinds(session)
    names = {k.kind for k in kinds}
    assert names == explain_svc.VALID_REASON_KINDS


# ---------------------------------------------------------------------------
# add_trace
# ---------------------------------------------------------------------------


def test_add_trace_basic(session):
    t = explain_svc.add_trace(
        session, target_kind="package", target_key="glibc",
        reason_kind="profile-explicit",
    )
    assert t.id is not None
    assert t.target_kind == "package"
    assert t.target_key == "glibc"
    assert t.reason_kind == "profile-explicit"


def test_add_trace_with_detail(session):
    t = explain_svc.add_trace(
        session, target_kind="config", target_key="/etc/fstab",
        reason_kind="layer", reason_detail="base-layer enforces mount table",
    )
    assert t.reason_detail == "base-layer enforces mount table"


def test_add_trace_with_build_id(session):
    t = explain_svc.add_trace(
        session, target_kind="service", target_key="sshd",
        reason_kind="security", build_id="fake-build-uuid",
    )
    assert t.build_id == "fake-build-uuid"


def test_add_trace_invalid_target_kind_raises(session):
    with pytest.raises(ValueError, match="Invalid target_kind"):
        explain_svc.add_trace(
            session, target_kind="bogus", target_key="x",
            reason_kind="group",
        )


def test_add_trace_invalid_reason_kind_raises(session):
    with pytest.raises(ValueError, match="Invalid reason_kind"):
        explain_svc.add_trace(
            session, target_kind="package", target_key="glibc",
            reason_kind="random-reason",
        )


def test_add_trace_all_target_kinds(session):
    for tk in sorted(explain_svc.VALID_TARGET_KINDS):
        t = explain_svc.add_trace(
            session, target_kind=tk, target_key=f"item-{tk}",
            reason_kind="dependency",
        )
        assert t.target_kind == tk


def test_add_trace_all_reason_kinds(session):
    for rk in sorted(explain_svc.VALID_REASON_KINDS):
        t = explain_svc.add_trace(
            session, target_kind="package", target_key=f"pkg-{rk}",
            reason_kind=rk,
        )
        assert t.reason_kind == rk


# ---------------------------------------------------------------------------
# explain_item
# ---------------------------------------------------------------------------


def test_explain_item_finds_traces(session):
    explain_svc.add_trace(
        session, target_kind="package", target_key="glibc",
        reason_kind="profile-explicit",
    )
    explain_svc.add_trace(
        session, target_kind="package", target_key="glibc",
        reason_kind="dependency", reason_detail="required by bash",
    )
    traces = explain_svc.explain_item(session, "glibc")
    assert len(traces) == 2


def test_explain_item_filter_by_kind(session):
    explain_svc.add_trace(session, target_kind="package", target_key="glibc",
                           reason_kind="group")
    explain_svc.add_trace(session, target_kind="config", target_key="glibc",
                           reason_kind="layer")
    pkg = explain_svc.explain_item(session, "glibc", target_kind="package")
    assert len(pkg) == 1


def test_explain_item_filter_by_build(session):
    explain_svc.add_trace(session, target_kind="package", target_key="glibc",
                           reason_kind="group", build_id="b1")
    explain_svc.add_trace(session, target_kind="package", target_key="glibc",
                           reason_kind="layer", build_id="b2")
    b1 = explain_svc.explain_item(session, "glibc", build_id="b1")
    assert len(b1) == 1 and b1[0].build_id == "b1"


def test_explain_item_not_found_empty(session):
    traces = explain_svc.explain_item(session, "nonexistent-key")
    assert traces == []


# ---------------------------------------------------------------------------
# explain_build
# ---------------------------------------------------------------------------


def test_explain_build_all_traces(session):
    for key in ["glibc", "bash", "openssh"]:
        explain_svc.add_trace(session, target_kind="package", target_key=key,
                               reason_kind="profile-explicit", build_id="build-xyz")
    explain_svc.add_trace(session, target_kind="package", target_key="curl",
                           reason_kind="dependency")
    traces = explain_svc.explain_build(session, "build-xyz")
    assert len(traces) == 3


def test_explain_build_empty(session):
    assert explain_svc.explain_build(session, "no-such-build") == []


def test_explain_build_ordered(session):
    explain_svc.add_trace(session, target_kind="service", target_key="sshd",
                           reason_kind="security", build_id="b99")
    explain_svc.add_trace(session, target_kind="package", target_key="glibc",
                           reason_kind="group", build_id="b99")
    traces = explain_svc.explain_build(session, "b99")
    kinds = [t.target_kind for t in traces]
    assert kinds == sorted(kinds)


# ---------------------------------------------------------------------------
# list_traces
# ---------------------------------------------------------------------------


def test_list_traces_empty(session):
    assert explain_svc.list_traces(session) == []


def test_list_traces_filter_by_build(session):
    explain_svc.add_trace(session, target_kind="package", target_key="a",
                           reason_kind="group", build_id="b1")
    explain_svc.add_trace(session, target_kind="package", target_key="b",
                           reason_kind="layer", build_id="b2")
    assert len(explain_svc.list_traces(session, build_id="b1")) == 1


def test_list_traces_filter_by_target_kind(session):
    explain_svc.add_trace(session, target_kind="package", target_key="a",
                           reason_kind="group")
    explain_svc.add_trace(session, target_kind="driver", target_key="b",
                           reason_kind="driver")
    assert len(explain_svc.list_traces(session, target_kind="driver")) == 1


def test_list_traces_filter_by_reason_kind(session):
    explain_svc.add_trace(session, target_kind="package", target_key="a",
                           reason_kind="override")
    explain_svc.add_trace(session, target_kind="package", target_key="b",
                           reason_kind="security")
    assert len(explain_svc.list_traces(session, reason_kind="override")) == 1


# ---------------------------------------------------------------------------
# render_explain_text
# ---------------------------------------------------------------------------


def test_render_empty(session):
    text = explain_svc.render_explain_text([])
    assert "No explain traces" in text


def test_render_shows_target(session):
    t = explain_svc.add_trace(session, target_kind="package", target_key="glibc",
                               reason_kind="profile-explicit")
    text = explain_svc.render_explain_text([t])
    assert "package:glibc" in text
    assert "profile-explicit" in text


def test_render_shows_detail(session):
    t = explain_svc.add_trace(session, target_kind="config", target_key="/etc/resolv.conf",
                               reason_kind="layer",
                               reason_detail="base layer sets DNS")
    text = explain_svc.render_explain_text([t])
    assert "base layer sets DNS" in text


def test_render_multiple_targets(session):
    t1 = explain_svc.add_trace(session, target_kind="package", target_key="bash",
                                reason_kind="group")
    t2 = explain_svc.add_trace(session, target_kind="service", target_key="sshd",
                                reason_kind="security")
    text = explain_svc.render_explain_text([t1, t2])
    assert "package:bash" in text
    assert "service:sshd" in text
