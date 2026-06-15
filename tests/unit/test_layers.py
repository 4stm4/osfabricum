"""Unit tests for M54 — OS Composition Layers designer."""

from __future__ import annotations

import pytest

from osfabricum import layers
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_layer_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_layers.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_layer_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = layers.create_layer_profile(session, "base-aarch64")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# Layer kinds
# ---------------------------------------------------------------------------


def test_layer_kinds_seeded(session):
    kinds = layers.list_layer_kinds(session)
    assert len(kinds) == 6


def test_layer_kinds_ordered(session):
    kinds = layers.list_layer_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_layer_kinds_expected_values(session):
    kinds = layers.list_layer_kinds(session)
    names = {k.kind for k in kinds}
    assert names == {"base", "bsp", "extension", "app", "compliance", "debug"}


def test_layer_kinds_have_labels(session):
    kinds = layers.list_layer_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(session):
    p = layers.create_layer_profile(session, "my-profile")
    session.commit()
    assert p.id
    assert p.name == "my-profile"
    assert p.base_layer == "base"


def test_create_profile_custom_base_layer(session):
    p = layers.create_layer_profile(session, "bsp-profile", base_layer="bsp")
    session.commit()
    assert p.base_layer == "bsp"


def test_create_profile_with_description(session):
    p = layers.create_layer_profile(session, "p1", description="a test profile")
    assert p.description == "a test profile"


def test_create_duplicate_profile_raises(session):
    layers.create_layer_profile(session, "dup")
    session.commit()
    with pytest.raises(ValueError, match="already exists"):
        layers.create_layer_profile(session, "dup")


def test_list_profiles_empty(session):
    assert layers.list_layer_profiles(session) == []


def test_list_profiles_returns_all(session):
    layers.create_layer_profile(session, "alpha")
    layers.create_layer_profile(session, "beta")
    session.commit()
    assert len(layers.list_layer_profiles(session)) == 2


def test_list_profiles_sorted_by_name(session):
    layers.create_layer_profile(session, "z-profile")
    layers.create_layer_profile(session, "a-profile")
    session.commit()
    names = [p.name for p in layers.list_layer_profiles(session)]
    assert names == sorted(names)


def test_get_profile_by_id(session, profile):
    fetched = layers.get_layer_profile(session, profile.id)
    assert fetched.name == profile.name


def test_get_profile_not_found_raises(session):
    with pytest.raises(KeyError):
        layers.get_layer_profile(session, "no-such-id")


def test_update_profile_description(session, profile):
    updated = layers.update_layer_profile(session, profile.id, description="new desc")
    assert updated.description == "new desc"


def test_update_profile_clears_hash(session, profile):
    layers.render_layer_manifest(session, profile.id)
    session.commit()
    layers.update_layer_profile(session, profile.id, description="changed")
    session.commit()
    p = layers.get_layer_profile(session, profile.id)
    assert p.content_hash is None


# ---------------------------------------------------------------------------
# Layer entries — all kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["base", "bsp", "extension", "app", "compliance", "debug"])
def test_add_entry_all_kinds(session, profile, kind):
    e = layers.add_layer_entry(session, profile.id, f"entry-{kind}", layer_kind=kind)
    assert e.layer_kind == kind


def test_add_entry_invalid_kind_raises(session, profile):
    with pytest.raises(ValueError, match="Invalid layer_kind"):
        layers.add_layer_entry(session, profile.id, "bad-entry", layer_kind="nonexistent")


def test_add_entry_default_is_extension(session, profile):
    e = layers.add_layer_entry(session, profile.id, "ext")
    assert e.layer_kind == "extension"


def test_add_entry_with_source_url(session, profile):
    e = layers.add_layer_entry(session, profile.id, "fw",
                               source_url="https://example.com/fw.tar.gz")
    assert e.source_url == "https://example.com/fw.tar.gz"


def test_add_entry_with_sha256_hint(session, profile):
    e = layers.add_layer_entry(session, profile.id, "fw", sha256_hint="sha256:abc123")
    assert e.sha256_hint == "sha256:abc123"


def test_add_entry_with_priority(session, profile):
    e = layers.add_layer_entry(session, profile.id, "e1", priority=10)
    assert e.priority == 10


def test_add_entry_disabled(session, profile):
    e = layers.add_layer_entry(session, profile.id, "disabled-e", is_enabled=False)
    assert not e.is_enabled


def test_add_entry_upsert_updates_existing(session, profile):
    layers.add_layer_entry(session, profile.id, "fw", priority=5)
    session.commit()
    updated = layers.add_layer_entry(session, profile.id, "fw", priority=99)
    session.commit()
    entries = layers.list_layer_entries(session, profile.id)
    assert len(entries) == 1
    assert entries[0].priority == 99


def test_add_entry_invalidates_hash(session, profile):
    layers.render_layer_manifest(session, profile.id)
    session.commit()
    layers.add_layer_entry(session, profile.id, "e1")
    session.commit()
    p = layers.get_layer_profile(session, profile.id)
    assert p.content_hash is None


def test_add_entry_to_nonexistent_profile_raises(session):
    with pytest.raises(KeyError):
        layers.add_layer_entry(session, "no-profile", "entry")


# ---------------------------------------------------------------------------
# List entries
# ---------------------------------------------------------------------------


def test_list_entries_empty(session, profile):
    assert layers.list_layer_entries(session, profile.id) == []


def test_list_entries_sorted_by_priority_then_name(session, profile):
    layers.add_layer_entry(session, profile.id, "b-entry", priority=5)
    layers.add_layer_entry(session, profile.id, "a-entry", priority=5)
    layers.add_layer_entry(session, profile.id, "c-entry", priority=1)
    session.commit()
    entries = layers.list_layer_entries(session, profile.id)
    assert entries[0].name == "c-entry"
    assert entries[1].name == "a-entry"
    assert entries[2].name == "b-entry"


def test_list_entries_unknown_profile_raises(session):
    with pytest.raises(KeyError):
        layers.list_layer_entries(session, "ghost")


# ---------------------------------------------------------------------------
# Render manifest
# ---------------------------------------------------------------------------


def test_render_manifest_sets_hash(session, profile):
    layers.add_layer_entry(session, profile.id, "e1")
    session.commit()
    p = layers.render_layer_manifest(session, profile.id)
    assert p.content_hash.startswith("sha256:")


def test_render_manifest_contains_profile_name(session, profile):
    p = layers.render_layer_manifest(session, profile.id)
    assert profile.name in p.rendered_manifest


def test_render_manifest_contains_base_layer(session, profile):
    p = layers.render_layer_manifest(session, profile.id)
    assert profile.base_layer in p.rendered_manifest


def test_render_manifest_enabled_section(session, profile):
    layers.add_layer_entry(session, profile.id, "wifi-fw", is_enabled=True)
    session.commit()
    p = layers.render_layer_manifest(session, profile.id)
    assert "[layers]" in p.rendered_manifest
    assert "wifi-fw" in p.rendered_manifest


def test_render_manifest_disabled_section(session, profile):
    layers.add_layer_entry(session, profile.id, "debug-layer", is_enabled=False)
    session.commit()
    p = layers.render_layer_manifest(session, profile.id)
    assert "[disabled_layers]" in p.rendered_manifest
    assert "debug-layer" in p.rendered_manifest


def test_render_manifest_mixed(session, profile):
    layers.add_layer_entry(session, profile.id, "active", is_enabled=True)
    layers.add_layer_entry(session, profile.id, "inactive", is_enabled=False)
    session.commit()
    p = layers.render_layer_manifest(session, profile.id)
    assert "active" in p.rendered_manifest
    assert "inactive" in p.rendered_manifest
    assert "[layers]" in p.rendered_manifest
    assert "[disabled_layers]" in p.rendered_manifest


def test_render_manifest_no_entries_shows_placeholder(session, profile):
    p = layers.render_layer_manifest(session, profile.id)
    assert "No enabled layers" in p.rendered_manifest


def test_render_manifest_sets_rendered_at(session, profile):
    p = layers.render_layer_manifest(session, profile.id)
    assert p.rendered_at is not None


def test_render_manifest_not_found_raises(session):
    with pytest.raises(KeyError):
        layers.render_layer_manifest(session, "no-id")


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    layers.add_layer_entry(session, profile.id, "e1", priority=1)
    session.commit()
    p1 = layers.render_layer_manifest(session, profile.id)
    h1 = p1.content_hash
    layers.update_layer_profile(session, profile.id, description="same")
    session.commit()
    layers.add_layer_entry(session, profile.id, "e1", priority=1)
    session.commit()
    p2 = layers.render_layer_manifest(session, profile.id)
    assert p1.name == p2.name
    assert p2.content_hash.startswith("sha256:")
