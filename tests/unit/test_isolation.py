"""Unit tests for M68 — Build Isolation / Sandbox Policies."""

from __future__ import annotations

import pytest

from osfabricum import isolation as iso_svc
from osfabricum.db.models import Base


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_isolation.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def policy(session):
    p = iso_svc.create_isolation_policy(
        session, name="default", mode="chroot",
        network_allowed=True, write_access="build-dir",
    )
    session.commit()
    return p


# ---------------------------------------------------------------------------
# create_isolation_policy
# ---------------------------------------------------------------------------

def test_create_policy(session):
    p = iso_svc.create_isolation_policy(session, name="strict", mode="bubblewrap")
    session.commit()
    assert p.id
    assert p.name == "strict"
    assert p.mode == "bubblewrap"
    assert p.network_allowed is True
    assert p.write_access == "build-dir"
    assert p.cache_mode == "ro"


def test_create_policy_invalid_mode(session):
    with pytest.raises(ValueError, match="Invalid mode"):
        iso_svc.create_isolation_policy(session, name="bad", mode="docker")


def test_create_policy_invalid_write_access(session):
    with pytest.raises(ValueError, match="Invalid write_access"):
        iso_svc.create_isolation_policy(session, name="bad", mode="none", write_access="anywhere")


# ---------------------------------------------------------------------------
# list_isolation_policies
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert iso_svc.list_isolation_policies(session) == []


def test_list_policies(session, policy):
    iso_svc.create_isolation_policy(session, name="vm-policy", mode="vm")
    session.commit()
    policies = iso_svc.list_isolation_policies(session)
    assert len(policies) == 2


# ---------------------------------------------------------------------------
# get_isolation_policy
# ---------------------------------------------------------------------------

def test_get_policy(session, policy):
    fetched = iso_svc.get_isolation_policy(session, policy.id)
    assert fetched.id == policy.id


def test_get_policy_missing(session):
    with pytest.raises(KeyError):
        iso_svc.get_isolation_policy(session, "nonexistent")


def test_get_policy_by_name(session, policy):
    fetched = iso_svc.get_isolation_policy_by_name(session, "default")
    assert fetched.id == policy.id


def test_get_policy_by_name_missing(session):
    result = iso_svc.get_isolation_policy_by_name(session, "unknown")
    assert result is None


# ---------------------------------------------------------------------------
# update_isolation_policy
# ---------------------------------------------------------------------------

def test_update_policy(session, policy):
    updated = iso_svc.update_isolation_policy(
        session, policy.id, mode="nspawn", network_allowed=False,
    )
    session.commit()
    assert updated.mode == "nspawn"
    assert updated.network_allowed is False


def test_update_policy_invalid_mode(session, policy):
    with pytest.raises(ValueError, match="Invalid mode"):
        iso_svc.update_isolation_policy(session, policy.id, mode="lxd")


def test_update_policy_missing(session):
    with pytest.raises(KeyError):
        iso_svc.update_isolation_policy(session, "nonexistent", mode="none")


# ---------------------------------------------------------------------------
# policy_satisfies
# ---------------------------------------------------------------------------

def test_policy_satisfies_same_level(session, policy):
    assert iso_svc.policy_satisfies(policy, "chroot") is True


def test_policy_satisfies_weaker_required(session, policy):
    assert iso_svc.policy_satisfies(policy, "none") is True


def test_policy_satisfies_stronger_required(session, policy):
    assert iso_svc.policy_satisfies(policy, "firecracker") is False


def test_policy_none_satisfies_none(session):
    p = iso_svc.create_isolation_policy(session, name="minimal", mode="none")
    session.commit()
    assert iso_svc.policy_satisfies(p, "none") is True
    assert iso_svc.policy_satisfies(p, "chroot") is False


def test_policy_vm_satisfies_all(session):
    p = iso_svc.create_isolation_policy(session, name="vm-pol", mode="vm")
    session.commit()
    for mode in ["none", "chroot", "bubblewrap", "nspawn", "podman", "firecracker", "vm"]:
        assert iso_svc.policy_satisfies(p, mode) is True


# ---------------------------------------------------------------------------
# add_recipe_requirement
# ---------------------------------------------------------------------------

def test_add_requirement(session):
    r = iso_svc.add_recipe_requirement(
        session, required_mode="bubblewrap",
        recipe_id="recipe-uuid-001", reason="Needs network isolation",
    )
    session.commit()
    assert r.id
    assert r.required_mode == "bubblewrap"
    assert r.recipe_id == "recipe-uuid-001"


def test_add_requirement_invalid_mode(session):
    with pytest.raises(ValueError, match="Invalid required_mode"):
        iso_svc.add_recipe_requirement(session, required_mode="docker")


def test_list_requirements(session):
    iso_svc.add_recipe_requirement(session, required_mode="chroot")
    iso_svc.add_recipe_requirement(session, required_mode="nspawn")
    session.commit()
    reqs = iso_svc.list_recipe_requirements(session)
    assert len(reqs) == 2
