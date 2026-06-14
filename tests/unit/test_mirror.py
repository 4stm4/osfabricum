"""Unit tests for M51 — Cache / Mirror / Offline designer."""

from __future__ import annotations

import pytest

from osfabricum import mirror
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_cache_policy_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_mirror.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_cache_policy_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = mirror.create_mirror_profile(session, "default-mirror")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# Cache policy kinds
# ---------------------------------------------------------------------------


def test_policy_kinds_seeded(session):
    kinds = mirror.list_cache_policy_kinds(session)
    assert len(kinds) == 4


def test_policy_kinds_ordered(session):
    kinds = mirror.list_cache_policy_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_policy_kinds_values(session):
    kinds = {k.kind for k in mirror.list_cache_policy_kinds(session)}
    assert kinds == {"always", "prefer", "bypass", "offline-only"}


def test_policy_kinds_have_labels(session):
    kinds = mirror.list_cache_policy_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


def test_policy_kinds_seed_idempotent(session):
    count = seed_cache_policy_kinds(session)
    assert count == 0


# ---------------------------------------------------------------------------
# Mirror profiles — CRUD
# ---------------------------------------------------------------------------


def test_create_profile_defaults(profile):
    assert profile.name == "default-mirror"
    assert profile.offline_mode is False
    assert profile.cache_ttl_days == 7
    assert profile.max_cache_size_mb is None
    assert profile.content_hash is None
    assert profile.distribution_id is None


def test_create_profile_offline(session):
    p = mirror.create_mirror_profile(
        session, "airgap",
        offline_mode=True,
        max_cache_size_mb=10240,
        cache_ttl_days=30,
    )
    session.commit()
    assert p.offline_mode is True
    assert p.max_cache_size_mb == 10240
    assert p.cache_ttl_days == 30


def test_create_profile_duplicate(session, profile):
    with pytest.raises(ValueError, match="already exists"):
        mirror.create_mirror_profile(session, "default-mirror")


def test_list_profiles(session, profile):
    mirror.create_mirror_profile(session, "second-mirror")
    session.commit()
    names = [p.name for p in mirror.list_mirror_profiles(session)]
    assert "default-mirror" in names
    assert "second-mirror" in names


def test_list_profiles_by_distribution(session):
    mirror.create_mirror_profile(session, "dist-mirror", distribution_id="dist-1")
    mirror.create_mirror_profile(session, "global-mirror")
    session.commit()
    dist = mirror.list_mirror_profiles(session, distribution_id="dist-1")
    assert len(dist) == 1
    assert dist[0].name == "dist-mirror"


def test_get_profile(session, profile):
    fetched = mirror.get_mirror_profile(session, profile.id)
    assert fetched.id == profile.id


def test_get_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.get_mirror_profile(session, "no-such-id")


def test_update_profile(session, profile):
    mirror.update_mirror_profile(
        session, profile.id,
        offline_mode=True,
        cache_ttl_days=14,
    )
    session.commit()
    p = mirror.get_mirror_profile(session, profile.id)
    assert p.offline_mode is True
    assert p.cache_ttl_days == 14


def test_update_profile_clears_hash(session, profile):
    profile.content_hash = "sha256:abc"
    session.flush()
    mirror.update_mirror_profile(session, profile.id, description="updated")
    session.commit()
    p = mirror.get_mirror_profile(session, profile.id)
    assert p.content_hash is None


def test_update_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.update_mirror_profile(session, "no-id", description="x")


# ---------------------------------------------------------------------------
# Mirror endpoints
# ---------------------------------------------------------------------------


def test_add_endpoint(session, profile):
    ep = mirror.add_mirror_endpoint(
        session, profile.id, "https://mirror.example.com"
    )
    session.commit()
    assert ep.url == "https://mirror.example.com"
    assert ep.is_default is False
    assert ep.requires_auth is False


def test_add_endpoint_with_options(session, profile):
    ep = mirror.add_mirror_endpoint(
        session, profile.id, "https://auth.mirror.com",
        priority=10, is_default=True, requires_auth=True, auth_token_id="tok-001"
    )
    session.commit()
    assert ep.priority == 10
    assert ep.is_default is True
    assert ep.requires_auth is True
    assert ep.auth_token_id == "tok-001"


def test_add_endpoint_upsert(session, profile):
    mirror.add_mirror_endpoint(session, profile.id, "https://mirror.example.com", priority=0)
    session.commit()
    mirror.add_mirror_endpoint(
        session, profile.id, "https://mirror.example.com", priority=5, is_default=True
    )
    session.commit()
    eps = mirror.list_mirror_endpoints(session, profile.id)
    assert len(eps) == 1
    assert eps[0].priority == 5
    assert eps[0].is_default is True


def test_add_endpoint_clears_hash(session, profile):
    mirror.render_mirror_config(session, profile.id)
    session.flush()
    mirror.add_mirror_endpoint(session, profile.id, "https://new.mirror.com")
    session.flush()
    p = mirror.get_mirror_profile(session, profile.id)
    assert p.content_hash is None


def test_list_endpoints_ordered(session, profile):
    for url, prio in (("https://c.com", 2), ("https://a.com", 0), ("https://b.com", 1)):
        mirror.add_mirror_endpoint(session, profile.id, url, priority=prio)
    session.commit()
    eps = mirror.list_mirror_endpoints(session, profile.id)
    priorities = [e.priority for e in eps]
    assert priorities == sorted(priorities)


def test_list_endpoints_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.list_mirror_endpoints(session, "no-id")


def test_add_endpoint_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.add_mirror_endpoint(session, "no-id", "https://x.com")


# ---------------------------------------------------------------------------
# Cache priority rules
# ---------------------------------------------------------------------------


def test_add_cache_rule(session, profile):
    rule = mirror.add_cache_rule(
        session, profile.id, "https://github.com/**", "always"
    )
    session.commit()
    assert rule.source_pattern == "https://github.com/**"
    assert rule.cache_policy == "always"
    assert rule.priority == 0


def test_add_cache_rule_all_policies(session, profile):
    for i, policy in enumerate(mirror.VALID_CACHE_POLICIES):
        rule = mirror.add_cache_rule(
            session, profile.id, f"https://host{i}.com/**", policy, priority=i
        )
        assert rule.cache_policy == policy


def test_add_cache_rule_upsert(session, profile):
    mirror.add_cache_rule(session, profile.id, "https://github.com/**", "prefer")
    session.commit()
    mirror.add_cache_rule(
        session, profile.id, "https://github.com/**", "offline-only", priority=5
    )
    session.commit()
    rules = mirror.list_cache_rules(session, profile.id)
    assert len(rules) == 1
    assert rules[0].cache_policy == "offline-only"
    assert rules[0].priority == 5


def test_add_cache_rule_invalid_policy(session, profile):
    with pytest.raises(ValueError, match="cache_policy"):
        mirror.add_cache_rule(session, profile.id, "https://x.com/**", "turbo")


def test_add_cache_rule_clears_hash(session, profile):
    mirror.render_mirror_config(session, profile.id)
    session.flush()
    mirror.add_cache_rule(session, profile.id, "https://new.com/**", "bypass")
    session.flush()
    p = mirror.get_mirror_profile(session, profile.id)
    assert p.content_hash is None


def test_list_rules_ordered(session, profile):
    for pat, prio in (("https://c.com/**", 2), ("https://a.com/**", 0), ("https://b.com/**", 1)):
        mirror.add_cache_rule(session, profile.id, pat, "prefer", priority=prio)
    session.commit()
    rules = mirror.list_cache_rules(session, profile.id)
    priorities = [r.priority for r in rules]
    assert priorities == sorted(priorities)


def test_list_rules_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.list_cache_rules(session, "no-id")


def test_add_rule_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.add_cache_rule(session, "no-id", "https://x.com/**", "prefer")


# ---------------------------------------------------------------------------
# Render — config content
# ---------------------------------------------------------------------------


def test_render_returns_hash(session, profile):
    p = mirror.render_mirror_config(session, profile.id)
    assert p.content_hash is not None
    assert p.content_hash.startswith("sha256:")


def test_render_mirror_section(session, profile):
    p = mirror.render_mirror_config(session, profile.id)
    assert "[mirror]" in p.rendered_mirror_config
    assert "offline_mode = false" in p.rendered_mirror_config
    assert "cache_ttl_days = 7" in p.rendered_mirror_config


def test_render_offline_mode(session):
    p = mirror.create_mirror_profile(session, "airgap", offline_mode=True)
    session.flush()
    p = mirror.render_mirror_config(session, p.id)
    assert "offline_mode = true" in p.rendered_mirror_config


def test_render_max_cache_size(session):
    p = mirror.create_mirror_profile(session, "limited", max_cache_size_mb=1024)
    session.flush()
    p = mirror.render_mirror_config(session, p.id)
    assert "max_cache_size_mb = 1024" in p.rendered_mirror_config


def test_render_endpoints_section(session, profile):
    mirror.add_mirror_endpoint(
        session, profile.id, "https://mirror.example.com",
        priority=0, is_default=True
    )
    session.flush()
    p = mirror.render_mirror_config(session, profile.id)
    assert "[endpoints]" in p.rendered_mirror_config
    assert "https://mirror.example.com" in p.rendered_mirror_config
    assert "(DEFAULT)" in p.rendered_mirror_config


def test_render_endpoints_sorted(session, profile):
    mirror.add_mirror_endpoint(session, profile.id, "https://z.com", priority=99)
    mirror.add_mirror_endpoint(session, profile.id, "https://a.com", priority=0)
    session.flush()
    p = mirror.render_mirror_config(session, profile.id)
    a_pos = p.rendered_mirror_config.index("https://a.com")
    z_pos = p.rendered_mirror_config.index("https://z.com")
    assert a_pos < z_pos


def test_render_no_endpoints_note(session, profile):
    p = mirror.render_mirror_config(session, profile.id)
    assert "No mirror endpoints defined" in p.rendered_mirror_config


def test_render_cache_rules_section(session, profile):
    mirror.add_cache_rule(session, profile.id, "https://github.com/**", "always")
    session.flush()
    p = mirror.render_mirror_config(session, profile.id)
    assert "[cache_rules]" in p.rendered_mirror_config
    assert "https://github.com/**" in p.rendered_mirror_config
    assert "always" in p.rendered_mirror_config


def test_render_no_rules_note(session, profile):
    p = mirror.render_mirror_config(session, profile.id)
    assert "No custom cache rules" in p.rendered_mirror_config


def test_render_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        mirror.render_mirror_config(session, "no-such-id")


# ---------------------------------------------------------------------------
# Render — determinism and caching
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    mirror.add_mirror_endpoint(session, profile.id, "https://m.example.com")
    session.flush()
    p1 = mirror.render_mirror_config(session, profile.id)
    h1 = p1.content_hash
    p2 = mirror.render_mirror_config(session, profile.id)
    assert p2.content_hash == h1


def test_render_stored(session, profile):
    p = mirror.render_mirror_config(session, profile.id)
    session.commit()
    fetched = mirror.get_mirror_profile(session, profile.id)
    assert fetched.content_hash == p.content_hash
    assert fetched.rendered_mirror_config is not None


def test_render_hash_changes_on_new_endpoint(session, profile):
    p1 = mirror.render_mirror_config(session, profile.id)
    h1 = p1.content_hash
    mirror.add_mirror_endpoint(session, profile.id, "https://new.mirror.com")
    session.flush()
    p2 = mirror.render_mirror_config(session, profile.id)
    assert p2.content_hash != h1


def test_render_hash_changes_on_new_rule(session, profile):
    p1 = mirror.render_mirror_config(session, profile.id)
    h1 = p1.content_hash
    mirror.add_cache_rule(session, profile.id, "https://new.com/**", "bypass")
    session.flush()
    p2 = mirror.render_mirror_config(session, profile.id)
    assert p2.content_hash != h1


def test_render_auth_endpoint_note(session, profile):
    mirror.add_mirror_endpoint(
        session, profile.id, "https://private.mirror.com",
        requires_auth=True
    )
    session.flush()
    p = mirror.render_mirror_config(session, profile.id)
    assert "[auth]" in p.rendered_mirror_config
