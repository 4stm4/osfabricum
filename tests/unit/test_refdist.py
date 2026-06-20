"""Unit tests for Phase 5 — Reference Distributions (M71/M72/M73)."""

from __future__ import annotations

import pytest

from osfabricum.db.models import Base
from osfabricum.db.seed_data import (
    seed_architectures_from_yaml,
    seed_boards_from_yaml,
    seed_distribution_classes,
    seed_distributions_from_yaml,
    seed_kernels_from_yaml,
    seed_netos_reference,
    seed_ocultum_reference,
    seed_tinywifi_reference,
    seed_toolchains_from_yaml,
)
from osfabricum.refdist import service as svc


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_refdist.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def seeded_session(db_engine):
    """Session with all three reference distributions seeded."""
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        seed_distribution_classes(s)
        seed_architectures_from_yaml(s)
        seed_boards_from_yaml(s)
        seed_toolchains_from_yaml(s)
        seed_kernels_from_yaml(s)
        seed_distributions_from_yaml(s)
        seed_tinywifi_reference(s)
        seed_netos_reference(s)
        seed_ocultum_reference(s)
        s.commit()
    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Catalog YAML loaders
# ---------------------------------------------------------------------------

def test_seed_architectures_from_yaml(session):
    n = seed_architectures_from_yaml(session)
    assert n >= 3
    from osfabricum.db.models import Architecture
    from sqlalchemy import select
    arches = session.scalars(select(Architecture)).all()
    names = {a.name for a in arches}
    assert "aarch64" in names
    assert "x86_64" in names
    assert "riscv64" in names


def test_seed_architectures_idempotent(session):
    n1 = seed_architectures_from_yaml(session)
    n2 = seed_architectures_from_yaml(session)
    assert n2 == 0
    assert n1 >= 3


def test_seed_boards_from_yaml(session):
    seed_architectures_from_yaml(session)
    n = seed_boards_from_yaml(session)
    assert n >= 1
    from osfabricum.db.models import Board
    from sqlalchemy import select
    boards = session.scalars(select(Board)).all()
    names = {b.name for b in boards}
    assert "rpi-zero-2w" in names


def test_seed_boards_idempotent(session):
    seed_architectures_from_yaml(session)
    n1 = seed_boards_from_yaml(session)
    n2 = seed_boards_from_yaml(session)
    assert n2 == 0
    assert n1 >= 1


def test_seed_toolchains_from_yaml(session):
    seed_architectures_from_yaml(session)
    n = seed_toolchains_from_yaml(session)
    assert n >= 1
    from osfabricum.db.models import Toolchain
    from sqlalchemy import select
    tcs = session.scalars(select(Toolchain)).all()
    names = {t.name for t in tcs}
    assert "aarch64-linux-musl-bootlin" in names


def test_seed_toolchains_idempotent(session):
    seed_architectures_from_yaml(session)
    n1 = seed_toolchains_from_yaml(session)
    n2 = seed_toolchains_from_yaml(session)
    assert n2 == 0
    assert n1 >= 1


def test_seed_kernels_from_yaml(session):
    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    n = seed_kernels_from_yaml(session)
    assert n >= 1
    from osfabricum.db.models import Kernel
    from sqlalchemy import select
    kernels = session.scalars(select(Kernel)).all()
    names = {k.name for k in kernels}
    assert "linux-rpi" in names


def test_seed_kernels_idempotent(session):
    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    n1 = seed_kernels_from_yaml(session)
    n2 = seed_kernels_from_yaml(session)
    assert n2 == 0
    assert n1 >= 1


def test_seed_distributions_from_yaml(session):
    seed_distribution_classes(session)
    n = seed_distributions_from_yaml(session)
    assert n >= 1
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dists = session.scalars(select(Distribution)).all()
    names = {d.name for d in dists}
    assert "tinywifi" in names
    assert "netos" in names
    assert "ocultum" in names


def test_seed_distributions_idempotent(session):
    seed_distribution_classes(session)
    n1 = seed_distributions_from_yaml(session)
    n2 = seed_distributions_from_yaml(session)
    assert n2 == 0
    assert n1 >= 1


# ---------------------------------------------------------------------------
# M71 — TinyWifi seed
# ---------------------------------------------------------------------------

def test_seed_tinywifi_reference_returns_counts(session):
    seed_distribution_classes(session)
    counts = seed_tinywifi_reference(session)
    assert counts["packages"] >= 7
    assert counts["groups"] >= 3
    assert counts["profiles"] >= 1


def test_seed_tinywifi_creates_distribution(session):
    seed_distribution_classes(session)
    seed_tinywifi_reference(session)
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "tinywifi")
    ).first()
    assert dist is not None
    assert "Wi-Fi" in (dist.description or "") or "wifi" in (dist.description or "").lower()


def test_seed_tinywifi_idempotent(session):
    seed_distribution_classes(session)
    counts1 = seed_tinywifi_reference(session)
    counts2 = seed_tinywifi_reference(session)
    assert counts2["profiles"] == 1


def test_seed_tinywifi_creates_profile(session):
    seed_distribution_classes(session)
    seed_tinywifi_reference(session)
    from osfabricum.db.models import Profile, Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "tinywifi")
    ).first()
    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id)
    ).all()
    assert len(profiles) >= 1
    assert profiles[0].name == "default"


def test_seed_tinywifi_packages_include_hostapd(session):
    seed_distribution_classes(session)
    seed_tinywifi_reference(session)
    from osfabricum.db.models import Package
    from sqlalchemy import select
    pkg = session.scalars(
        select(Package).where(Package.name == "hostapd")
    ).first()
    assert pkg is not None


# ---------------------------------------------------------------------------
# M72 — NetOS seed
# ---------------------------------------------------------------------------

def test_seed_netos_reference_returns_counts(session):
    seed_distribution_classes(session)
    counts = seed_netos_reference(session)
    assert counts["packages"] >= 5
    assert counts["groups"] >= 3
    assert counts["sets"] >= 2
    assert counts["profiles"] >= 2


def test_seed_netos_creates_distribution(session):
    seed_distribution_classes(session)
    seed_netos_reference(session)
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "netos")
    ).first()
    assert dist is not None


def test_seed_netos_idempotent(session):
    seed_distribution_classes(session)
    seed_netos_reference(session)
    seed_netos_reference(session)
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dists = session.scalars(
        select(Distribution).where(Distribution.name == "netos")
    ).all()
    assert len(dists) == 1


def test_seed_netos_has_sdn_packages(session):
    seed_distribution_classes(session)
    seed_netos_reference(session)
    from osfabricum.db.models import Package
    from sqlalchemy import select
    pkg = session.scalars(
        select(Package).where(Package.name == "ovs-vswitchd")
    ).first()
    assert pkg is not None


def test_seed_netos_profiles_include_nervum(session):
    seed_distribution_classes(session)
    seed_netos_reference(session)
    from osfabricum.db.models import Profile, Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "netos")
    ).first()
    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id)
    ).all()
    names = {p.name for p in profiles}
    assert "nervum" in names


# ---------------------------------------------------------------------------
# M73 — Ocultum seed
# ---------------------------------------------------------------------------

def test_seed_ocultum_reference_returns_counts(session):
    seed_distribution_classes(session)
    counts = seed_ocultum_reference(session)
    assert counts["packages"] >= 5
    assert counts["groups"] >= 4
    assert counts["sets"] >= 2
    assert counts["profiles"] >= 2


def test_seed_ocultum_creates_distribution(session):
    seed_distribution_classes(session)
    seed_ocultum_reference(session)
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "ocultum")
    ).first()
    assert dist is not None


def test_seed_ocultum_has_wayland(session):
    seed_distribution_classes(session)
    seed_ocultum_reference(session)
    from osfabricum.db.models import Package
    from sqlalchemy import select
    pkg = session.scalars(
        select(Package).where(Package.name == "wayland")
    ).first()
    assert pkg is not None


def test_seed_ocultum_idempotent(session):
    seed_distribution_classes(session)
    seed_ocultum_reference(session)
    seed_ocultum_reference(session)
    from osfabricum.db.models import Distribution
    from sqlalchemy import select
    dists = session.scalars(
        select(Distribution).where(Distribution.name == "ocultum")
    ).all()
    assert len(dists) == 1


def test_seed_ocultum_profiles_include_communicator(session):
    seed_distribution_classes(session)
    seed_ocultum_reference(session)
    from osfabricum.db.models import Profile, Distribution
    from sqlalchemy import select
    dist = session.scalars(
        select(Distribution).where(Distribution.name == "ocultum")
    ).first()
    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id)
    ).all()
    names = {p.name for p in profiles}
    assert "communicator" in names


# ---------------------------------------------------------------------------
# service.py — list / get / profiles / validate
# ---------------------------------------------------------------------------

def test_list_reference_distributions(seeded_session):
    items = svc.list_reference_distributions(seeded_session)
    assert len(items) == 3
    names = {d.name for d in items}
    assert names == {"tinywifi", "netos", "ocultum"}


def test_list_reference_distributions_empty(session):
    # No seed data — should return empty list gracefully
    items = svc.list_reference_distributions(session)
    assert items == []


def test_get_reference_distribution_tinywifi(seeded_session):
    d = svc.get_reference_distribution(seeded_session, "tinywifi")
    assert d is not None
    assert d.name == "tinywifi"
    assert d.class_name == "router"
    assert d.package_count > 0


def test_get_reference_distribution_netos(seeded_session):
    d = svc.get_reference_distribution(seeded_session, "netos")
    assert d is not None
    assert d.class_name == "server"
    assert d.group_count >= 4


def test_get_reference_distribution_ocultum(seeded_session):
    d = svc.get_reference_distribution(seeded_session, "ocultum")
    assert d is not None
    assert d.class_name == "mobile-handheld"


def test_get_reference_distribution_not_found(seeded_session):
    d = svc.get_reference_distribution(seeded_session, "doesnotexist")
    assert d is None


def test_list_reference_profiles_tinywifi(seeded_session):
    profiles = svc.list_reference_profiles(seeded_session, "tinywifi")
    assert len(profiles) >= 1
    assert profiles[0].name == "default"
    assert profiles[0].board_name == "rpi-zero-2w"
    assert profiles[0].arch_name == "aarch64"
    assert len(profiles[0].packages) >= 5


def test_list_reference_profiles_netos(seeded_session):
    profiles = svc.list_reference_profiles(seeded_session, "netos")
    assert len(profiles) >= 2
    names = {p.name for p in profiles}
    assert "nervum" in names
    assert "ovsdb" in names


def test_list_reference_profiles_not_found(seeded_session):
    profiles = svc.list_reference_profiles(seeded_session, "unknown")
    assert profiles == []


def test_validate_tinywifi_valid(seeded_session):
    result = svc.validate_reference_distribution(seeded_session, "tinywifi")
    assert result["valid"] is True
    assert result["profiles"] >= 1
    assert result["packages"] >= 5
    assert result["errors"] == []


def test_validate_netos_valid(seeded_session):
    result = svc.validate_reference_distribution(seeded_session, "netos")
    assert result["valid"] is True


def test_validate_ocultum_valid(seeded_session):
    result = svc.validate_reference_distribution(seeded_session, "ocultum")
    assert result["valid"] is True


def test_validate_not_found(seeded_session):
    result = svc.validate_reference_distribution(seeded_session, "nonexistent")
    assert result["valid"] is False
    assert any("not found" in e for e in result["errors"])


def test_all_three_dists_coexist(seeded_session):
    """All three reference distributions coexist without conflicts."""
    items = svc.list_reference_distributions(seeded_session)
    assert len(items) == 3
    for item in items:
        assert item.package_count > 0
        assert item.group_count > 0
        assert len(item.profiles) > 0
