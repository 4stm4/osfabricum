"""Unit tests for M55 — Override / Masking engine."""

from __future__ import annotations

import pytest

from osfabricum import overrides
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_override_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_overrides.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_override_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = overrides.create_override_profile(session, "default-overrides")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# Override kinds
# ---------------------------------------------------------------------------


def test_override_kinds_seeded(session):
    kinds = overrides.list_override_kinds(session)
    assert len(kinds) == 6


def test_override_kinds_ordered(session):
    kinds = overrides.list_override_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_override_kinds_expected_values(session):
    kinds = overrides.list_override_kinds(session)
    names = {k.kind for k in kinds}
    assert names == {"set", "unset", "mask", "append", "prepend", "replace"}


def test_override_kinds_have_labels(session):
    kinds = overrides.list_override_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(session):
    p = overrides.create_override_profile(session, "prod-overrides")
    session.commit()
    assert p.id
    assert p.name == "prod-overrides"


def test_create_profile_with_description(session):
    p = overrides.create_override_profile(session, "p1", description="security hardening")
    assert p.description == "security hardening"


def test_create_duplicate_profile_raises(session):
    overrides.create_override_profile(session, "dup")
    session.commit()
    with pytest.raises(ValueError, match="already exists"):
        overrides.create_override_profile(session, "dup")


def test_list_profiles_empty(session):
    assert overrides.list_override_profiles(session) == []


def test_list_profiles_returns_all(session):
    overrides.create_override_profile(session, "a")
    overrides.create_override_profile(session, "b")
    session.commit()
    assert len(overrides.list_override_profiles(session)) == 2


def test_list_profiles_sorted_by_name(session):
    overrides.create_override_profile(session, "z-profile")
    overrides.create_override_profile(session, "a-profile")
    session.commit()
    names = [p.name for p in overrides.list_override_profiles(session)]
    assert names == sorted(names)


def test_get_profile_by_id(session, profile):
    fetched = overrides.get_override_profile(session, profile.id)
    assert fetched.name == profile.name


def test_get_profile_not_found_raises(session):
    with pytest.raises(KeyError):
        overrides.get_override_profile(session, "missing-id")


def test_update_profile_description(session, profile):
    updated = overrides.update_override_profile(session, profile.id, description="updated")
    assert updated.description == "updated"


def test_update_profile_clears_hash(session, profile):
    overrides.render_override_policy(session, profile.id)
    session.commit()
    overrides.update_override_profile(session, profile.id, description="changed")
    session.commit()
    p = overrides.get_override_profile(session, profile.id)
    assert p.content_hash is None


# ---------------------------------------------------------------------------
# Rules — all actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["set", "unset", "mask", "append", "prepend", "replace"])
def test_add_rule_all_actions(session, profile, action):
    r = overrides.add_override_rule(
        session, profile.id, "sysctl", "net.ipv4.ip_forward", action=action
    )
    assert r.action == action


def test_add_rule_invalid_action_raises(session, profile):
    with pytest.raises(ValueError, match="Invalid action"):
        overrides.add_override_rule(
            session, profile.id, "sysctl", "key", action="bad-action"
        )


# ---------------------------------------------------------------------------
# Rules — all target types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ttype", ["package", "config", "kernel-param", "service", "sysctl"])
def test_add_rule_all_target_types(session, profile, ttype):
    r = overrides.add_override_rule(session, profile.id, ttype, "some-key")
    assert r.target_type == ttype


def test_add_rule_invalid_target_type_raises(session, profile):
    with pytest.raises(ValueError, match="Invalid target_type"):
        overrides.add_override_rule(session, profile.id, "invalid-type", "key")


def test_add_rule_with_value(session, profile):
    r = overrides.add_override_rule(
        session, profile.id, "sysctl", "vm.swappiness", action="set", value="10"
    )
    assert r.value == "10"


def test_add_rule_without_value(session, profile):
    r = overrides.add_override_rule(session, profile.id, "service", "sshd", action="mask")
    assert r.value is None


def test_add_rule_with_reason(session, profile):
    r = overrides.add_override_rule(
        session, profile.id, "sysctl", "key", reason="security requirement"
    )
    assert r.reason == "security requirement"


def test_add_rule_with_priority(session, profile):
    r = overrides.add_override_rule(session, profile.id, "package", "vim", priority=5)
    assert r.priority == 5


def test_add_rule_nonexistent_profile_raises(session):
    with pytest.raises(KeyError):
        overrides.add_override_rule(session, "ghost-id", "sysctl", "key")


# ---------------------------------------------------------------------------
# Upsert behaviour
# ---------------------------------------------------------------------------


def test_add_rule_upsert_updates_existing(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "key", value="old")
    session.commit()
    overrides.add_override_rule(session, profile.id, "sysctl", "key", value="new")
    session.commit()
    rules = overrides.list_override_rules(session, profile.id)
    assert len(rules) == 1
    assert rules[0].value == "new"


def test_add_rule_upsert_invalidates_hash(session, profile):
    overrides.render_override_policy(session, profile.id)
    session.commit()
    overrides.add_override_rule(session, profile.id, "sysctl", "key")
    session.commit()
    p = overrides.get_override_profile(session, profile.id)
    assert p.content_hash is None


# ---------------------------------------------------------------------------
# List rules
# ---------------------------------------------------------------------------


def test_list_rules_empty(session, profile):
    assert overrides.list_override_rules(session, profile.id) == []


def test_list_rules_returns_all(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "a")
    overrides.add_override_rule(session, profile.id, "package", "b")
    overrides.add_override_rule(session, profile.id, "service", "c")
    session.commit()
    assert len(overrides.list_override_rules(session, profile.id)) == 3


def test_list_rules_filter_by_target_type(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "s1")
    overrides.add_override_rule(session, profile.id, "sysctl", "s2")
    overrides.add_override_rule(session, profile.id, "package", "p1")
    session.commit()
    sysctl_rules = overrides.list_override_rules(session, profile.id, target_type="sysctl")
    assert len(sysctl_rules) == 2
    assert all(r.target_type == "sysctl" for r in sysctl_rules)


def test_list_rules_filter_config(session, profile):
    overrides.add_override_rule(session, profile.id, "config", "cfg.key", value="v")
    overrides.add_override_rule(session, profile.id, "sysctl", "other")
    session.commit()
    cfg_rules = overrides.list_override_rules(session, profile.id, target_type="config")
    assert len(cfg_rules) == 1
    assert cfg_rules[0].target_key == "cfg.key"


def test_list_rules_sorted_by_type_then_priority(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "b", priority=10)
    overrides.add_override_rule(session, profile.id, "sysctl", "a", priority=1)
    overrides.add_override_rule(session, profile.id, "package", "x", priority=5)
    session.commit()
    rules = overrides.list_override_rules(session, profile.id)
    types = [r.target_type for r in rules]
    assert types == sorted(types)


def test_list_rules_unknown_profile_raises(session):
    with pytest.raises(KeyError):
        overrides.list_override_rules(session, "ghost")


# ---------------------------------------------------------------------------
# Render policy
# ---------------------------------------------------------------------------


def test_render_sets_content_hash(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "key")
    session.commit()
    p = overrides.render_override_policy(session, profile.id)
    assert p.content_hash.startswith("sha256:")


def test_render_contains_profile_name(session, profile):
    p = overrides.render_override_policy(session, profile.id)
    assert profile.name in p.rendered_override_policy


def test_render_groups_by_target_type(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "vm.swappiness", value="10")
    overrides.add_override_rule(session, profile.id, "package", "vim", action="unset")
    session.commit()
    p = overrides.render_override_policy(session, profile.id)
    policy = p.rendered_override_policy
    assert "[sysctl]" in policy
    assert "[package]" in policy
    assert "vm.swappiness" in policy
    assert "vim" in policy


def test_render_empty_profile_no_rules_msg(session, profile):
    p = overrides.render_override_policy(session, profile.id)
    assert "No override rules" in p.rendered_override_policy


def test_render_sets_rendered_at(session, profile):
    p = overrides.render_override_policy(session, profile.id)
    assert p.rendered_at is not None


def test_render_not_found_raises(session):
    with pytest.raises(KeyError):
        overrides.render_override_policy(session, "no-such-id")


def test_render_kernel_param_section(session, profile):
    overrides.add_override_rule(
        session, profile.id, "kernel-param", "console", action="set", value="ttyS0"
    )
    session.commit()
    p = overrides.render_override_policy(session, profile.id)
    assert "[kernel-param]" in p.rendered_override_policy
    assert "console" in p.rendered_override_policy


def test_render_service_section(session, profile):
    overrides.add_override_rule(session, profile.id, "service", "bluetooth", action="mask")
    session.commit()
    p = overrides.render_override_policy(session, profile.id)
    assert "[service]" in p.rendered_override_policy
    assert "bluetooth" in p.rendered_override_policy


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    overrides.add_override_rule(session, profile.id, "sysctl", "net.ipv4.ip_forward",
                                action="set", value="1")
    session.commit()
    p1 = overrides.render_override_policy(session, profile.id)
    h1 = p1.content_hash

    p2 = overrides.render_override_policy(session, profile.id)
    assert p2.content_hash == h1
