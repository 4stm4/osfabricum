"""Unit tests for M66 — Boot / Performance Profiler."""

from __future__ import annotations

import pytest

from osfabricum import bootprofiler as bp_svc
from osfabricum.db.models import Base

BUILD_ID = "build-uuid-0066"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_bootprofiler.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = bp_svc.create_boot_profile(session, build_id=BUILD_ID, capture_method="qemu")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# create_boot_profile
# ---------------------------------------------------------------------------

def test_create_profile(session):
    p = bp_svc.create_boot_profile(session, build_id=BUILD_ID, capture_method="qemu")
    session.commit()
    assert p.id
    assert p.build_id == BUILD_ID
    assert p.capture_method == "qemu"
    assert p.total_boot_ms is None


def test_create_profile_invalid_method(session):
    with pytest.raises(ValueError, match="Invalid capture_method"):
        bp_svc.create_boot_profile(session, build_id=BUILD_ID, capture_method="magic")


# ---------------------------------------------------------------------------
# add_boot_sample
# ---------------------------------------------------------------------------

def test_add_sample(session, profile):
    s = bp_svc.add_boot_sample(
        session, boot_profile_id=profile.id,
        event_kind="kernel-init", event_name="boot_start",
        timestamp_ms=0, duration_ms=500,
    )
    session.commit()
    assert s.id
    assert s.event_kind == "kernel-init"
    assert s.timestamp_ms == 0


def test_add_sample_clears_hash(session, profile):
    bp_svc.add_boot_sample(session, profile.id, "kernel-init", "init", 0)
    bp_svc.render_boot_timeline(session, profile.id)
    session.commit()
    assert profile.content_hash is not None
    bp_svc.add_boot_sample(session, profile.id, "userspace", "login", 3000)
    session.commit()
    assert profile.content_hash is None


def test_add_sample_invalid_kind(session, profile):
    with pytest.raises(ValueError, match="Invalid event_kind"):
        bp_svc.add_boot_sample(session, profile.id, "unknown-phase", "x", 0)


def test_add_sample_critical_path(session, profile):
    s = bp_svc.add_boot_sample(
        session, profile.id, "service-start", "network.target",
        timestamp_ms=800, duration_ms=200, is_critical_path=True,
    )
    session.commit()
    assert s.is_critical_path is True


# ---------------------------------------------------------------------------
# list_boot_samples
# ---------------------------------------------------------------------------

def test_list_samples_ordered(session, profile):
    bp_svc.add_boot_sample(session, profile.id, "kernel-init", "start", 0)
    bp_svc.add_boot_sample(session, profile.id, "service-start", "sshd", 2000)
    bp_svc.add_boot_sample(session, profile.id, "userspace", "login", 3500)
    session.commit()
    samples = bp_svc.list_boot_samples(session, profile.id)
    assert len(samples) == 3
    timestamps = [s.timestamp_ms for s in samples]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# list_boot_profiles
# ---------------------------------------------------------------------------

def test_list_profiles(session, profile):
    bp_svc.create_boot_profile(session, build_id=BUILD_ID, capture_method="serial")
    session.commit()
    profiles = bp_svc.list_boot_profiles(session, build_id=BUILD_ID)
    assert len(profiles) == 2


def test_list_profiles_empty(session):
    assert bp_svc.list_boot_profiles(session, build_id="unknown") == []


# ---------------------------------------------------------------------------
# get_boot_profile
# ---------------------------------------------------------------------------

def test_get_profile(session, profile):
    fetched = bp_svc.get_boot_profile(session, profile.id)
    assert fetched.id == profile.id


def test_get_profile_missing(session):
    with pytest.raises(KeyError):
        bp_svc.get_boot_profile(session, "nonexistent")


# ---------------------------------------------------------------------------
# render_boot_timeline
# ---------------------------------------------------------------------------

def test_render_timeline_empty(session, profile):
    p = bp_svc.render_boot_timeline(session, profile.id)
    session.commit()
    assert p.content_hash is not None
    assert p.total_boot_ms == 0


def test_render_timeline_with_samples(session, profile):
    bp_svc.add_boot_sample(session, profile.id, "kernel-init", "start", 0, 200, True)
    bp_svc.add_boot_sample(session, profile.id, "service-start", "systemd", 200, 800, True)
    bp_svc.add_boot_sample(session, profile.id, "target-reached", "multi-user", 1000, 0)
    session.commit()
    p = bp_svc.render_boot_timeline(session, profile.id)
    session.commit()
    assert "start" in (p.rendered_timeline or "")
    assert p.total_boot_ms == 1000


def test_render_deterministic(session, profile):
    bp_svc.add_boot_sample(session, profile.id, "kernel-init", "x", 0, 100)
    session.commit()
    h1 = bp_svc.render_boot_timeline(session, profile.id).content_hash
    session.commit()
    h2 = bp_svc.render_boot_timeline(session, profile.id).content_hash
    assert h1 == h2
