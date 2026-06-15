"""Unit tests for M56 — Patch Queue / Source Patch Manager."""

from __future__ import annotations

import pytest

from osfabricum import patches
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_patch_target_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_patches.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_patch_target_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def patch_set(session):
    ps = patches.create_patch_set(session, "kernel-hardening", target_kind="kernel")
    session.commit()
    return ps


# ---------------------------------------------------------------------------
# Target kinds
# ---------------------------------------------------------------------------


def test_target_kinds_seeded(session):
    kinds = patches.list_patch_target_kinds(session)
    assert len(kinds) == 5


def test_target_kinds_ordered(session):
    kinds = patches.list_patch_target_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_target_kinds_expected_values(session):
    kinds = patches.list_patch_target_kinds(session)
    names = {k.kind for k in kinds}
    assert names == {
        "kernel", "package-source", "branding", "config-template", "build-recipe"
    }


def test_target_kinds_have_labels(session):
    kinds = patches.list_patch_target_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


# ---------------------------------------------------------------------------
# Patch set CRUD
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [
    "kernel", "package-source", "branding", "config-template", "build-recipe"
])
def test_create_patch_set_all_target_kinds(session, kind):
    ps = patches.create_patch_set(session, f"ps-{kind}", target_kind=kind)
    session.commit()
    assert ps.target_kind == kind


def test_create_patch_set_defaults(session):
    ps = patches.create_patch_set(session, "default-set")
    assert ps.target_kind == "kernel"
    assert ps.description == ""


def test_create_patch_set_with_description(session):
    ps = patches.create_patch_set(session, "p1", description="my patches")
    assert ps.description == "my patches"


def test_create_patch_set_invalid_kind_raises(session):
    with pytest.raises(ValueError, match="Invalid target_kind"):
        patches.create_patch_set(session, "bad", target_kind="nonsense")


def test_create_duplicate_patch_set_raises(session):
    patches.create_patch_set(session, "dup")
    session.commit()
    with pytest.raises(ValueError, match="already exists"):
        patches.create_patch_set(session, "dup")


def test_list_patch_sets_empty(session):
    assert patches.list_patch_sets(session) == []


def test_list_patch_sets_returns_all(session):
    patches.create_patch_set(session, "a")
    patches.create_patch_set(session, "b")
    session.commit()
    assert len(patches.list_patch_sets(session)) == 2


def test_list_patch_sets_sorted_by_name(session):
    patches.create_patch_set(session, "z-set")
    patches.create_patch_set(session, "a-set")
    session.commit()
    names = [ps.name for ps in patches.list_patch_sets(session)]
    assert names == sorted(names)


def test_get_patch_set_by_id(session, patch_set):
    fetched = patches.get_patch_set(session, patch_set.id)
    assert fetched.id == patch_set.id


def test_get_patch_set_not_found_raises(session):
    with pytest.raises(KeyError):
        patches.get_patch_set(session, "no-such-id")


def test_update_patch_set_description(session, patch_set):
    updated = patches.update_patch_set(session, patch_set.id, description="updated")
    assert updated.description == "updated"


def test_update_patch_set_clears_hash(session, patch_set):
    patches.render_patch_manifest(session, patch_set.id)
    session.commit()
    patches.update_patch_set(session, patch_set.id, description="changed")
    session.commit()
    ps = patches.get_patch_set(session, patch_set.id)
    assert ps.content_hash is None


def test_patch_set_has_timestamps(session, patch_set):
    assert patch_set.created_at is not None
    assert patch_set.updated_at is not None


# ---------------------------------------------------------------------------
# Patches — add / upsert
# ---------------------------------------------------------------------------


def test_add_patch_minimal(session, patch_set):
    p = patches.add_patch(session, patch_set.id, sequence_num=10, name="0001-fix.patch")
    session.commit()
    assert p.id
    assert p.sequence_num == 10
    assert p.name == "0001-fix.patch"
    assert p.patch_format == "diff"
    assert p.is_enabled is True


def test_add_patch_with_content(session, patch_set):
    content = "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n"
    p = patches.add_patch(session, patch_set.id, 10, "fix.patch", patch_content=content)
    assert p.patch_content == content


@pytest.mark.parametrize("fmt", ["diff", "quilt", "git-am"])
def test_add_patch_all_formats(session, patch_set, fmt):
    p = patches.add_patch(session, patch_set.id, 10, f"p.{fmt}", patch_format=fmt)
    assert p.patch_format == fmt


def test_add_patch_invalid_format_raises(session, patch_set):
    with pytest.raises(ValueError, match="Invalid patch_format"):
        patches.add_patch(session, patch_set.id, 10, "bad.patch", patch_format="wrong")


def test_add_patch_disabled(session, patch_set):
    p = patches.add_patch(session, patch_set.id, 10, "disabled.patch", is_enabled=False)
    assert p.is_enabled is False


def test_add_patch_upsert_updates_existing(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "old-name.patch")
    session.commit()
    updated = patches.add_patch(session, patch_set.id, 10, "new-name.patch")
    session.commit()
    all_patches = patches.list_patches(session, patch_set.id)
    assert len(all_patches) == 1
    assert all_patches[0].name == "new-name.patch"


def test_add_patch_upsert_invalidates_hash(session, patch_set):
    patches.render_patch_manifest(session, patch_set.id)
    session.commit()
    patches.add_patch(session, patch_set.id, 10, "new.patch")
    session.commit()
    ps = patches.get_patch_set(session, patch_set.id)
    assert ps.content_hash is None


def test_add_patch_nonexistent_set_raises(session):
    with pytest.raises(KeyError):
        patches.add_patch(session, "ghost-id", 1, "p.patch")


def test_add_multiple_patches_different_seqs(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "a.patch")
    patches.add_patch(session, patch_set.id, 20, "b.patch")
    patches.add_patch(session, patch_set.id, 30, "c.patch")
    session.commit()
    all_patches = patches.list_patches(session, patch_set.id)
    assert len(all_patches) == 3


# ---------------------------------------------------------------------------
# List patches
# ---------------------------------------------------------------------------


def test_list_patches_empty(session, patch_set):
    assert patches.list_patches(session, patch_set.id) == []


def test_list_patches_ordered_by_seq(session, patch_set):
    patches.add_patch(session, patch_set.id, 30, "c.patch")
    patches.add_patch(session, patch_set.id, 10, "a.patch")
    patches.add_patch(session, patch_set.id, 20, "b.patch")
    session.commit()
    all_patches = patches.list_patches(session, patch_set.id)
    seqs = [p.sequence_num for p in all_patches]
    assert seqs == [10, 20, 30]


def test_list_patches_unknown_set_raises(session):
    with pytest.raises(KeyError):
        patches.list_patches(session, "ghost")


# ---------------------------------------------------------------------------
# Render manifest
# ---------------------------------------------------------------------------


def test_render_sets_content_hash(session, patch_set):
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert ps.content_hash.startswith("sha256:")


def test_render_contains_patch_set_name(session, patch_set):
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert patch_set.name in ps.rendered_patch_manifest


def test_render_contains_target_kind(session, patch_set):
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert patch_set.target_kind in ps.rendered_patch_manifest


def test_render_lists_enabled_patches(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "enable-net.patch", is_enabled=True)
    session.commit()
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert "enable-net.patch" in ps.rendered_patch_manifest
    assert "[patches]" in ps.rendered_patch_manifest


def test_render_lists_disabled_patches_separately(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "exp.patch", is_enabled=False)
    session.commit()
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert "[disabled_patches]" in ps.rendered_patch_manifest
    assert "exp.patch" in ps.rendered_patch_manifest


def test_render_mixed_enabled_disabled(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "on.patch", is_enabled=True)
    patches.add_patch(session, patch_set.id, 20, "off.patch", is_enabled=False)
    session.commit()
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert "[patches]" in ps.rendered_patch_manifest
    assert "[disabled_patches]" in ps.rendered_patch_manifest
    assert "on.patch" in ps.rendered_patch_manifest
    assert "off.patch" in ps.rendered_patch_manifest


def test_render_no_patches_shows_placeholder(session, patch_set):
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert "No enabled patches" in ps.rendered_patch_manifest


def test_render_sets_rendered_at(session, patch_set):
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert ps.rendered_at is not None


def test_render_not_found_raises(session):
    with pytest.raises(KeyError):
        patches.render_patch_manifest(session, "no-id")


def test_render_shows_sequence_numbers(session, patch_set):
    patches.add_patch(session, patch_set.id, 42, "the-patch.patch")
    session.commit()
    ps = patches.render_patch_manifest(session, patch_set.id)
    assert "0042" in ps.rendered_patch_manifest


# ---------------------------------------------------------------------------
# Application results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "success", "failed", "partial"])
def test_record_application_all_statuses(session, patch_set, status):
    r = patches.record_application(session, patch_set.id, status=status)
    assert r.status == status


def test_record_application_invalid_status_raises(session, patch_set):
    with pytest.raises(ValueError, match="Invalid status"):
        patches.record_application(session, patch_set.id, status="wrong")


def test_record_application_with_count(session, patch_set):
    r = patches.record_application(session, patch_set.id, applied_count=3)
    assert r.applied_count == 3


def test_record_application_failed_at_sequence(session, patch_set):
    r = patches.record_application(
        session, patch_set.id, status="failed", applied_count=2, failed_at_sequence=30
    )
    assert r.failed_at_sequence == 30


def test_record_application_with_error_message(session, patch_set):
    r = patches.record_application(
        session, patch_set.id, status="failed", error_message="hunk failed"
    )
    assert r.error_message == "hunk failed"


def test_record_application_nonexistent_set_raises(session):
    with pytest.raises(KeyError):
        patches.record_application(session, "ghost-id")


def test_list_application_results_empty(session, patch_set):
    assert patches.list_application_results(session, patch_set.id) == []


def test_list_application_results_multiple(session, patch_set):
    patches.record_application(session, patch_set.id, status="success")
    patches.record_application(session, patch_set.id, status="failed")
    session.commit()
    results = patches.list_application_results(session, patch_set.id)
    assert len(results) == 2


def test_list_application_results_ordered_by_applied_at_desc(session, patch_set):
    patches.record_application(session, patch_set.id, status="success")
    patches.record_application(session, patch_set.id, status="failed")
    session.commit()
    results = patches.list_application_results(session, patch_set.id)
    # Most recent first
    assert results[0].applied_at >= results[-1].applied_at


def test_list_application_results_unknown_set_raises(session):
    with pytest.raises(KeyError):
        patches.list_application_results(session, "ghost")


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_render_deterministic(session, patch_set):
    patches.add_patch(session, patch_set.id, 10, "stable.patch",
                      patch_content="--- a\n+++ b\n")
    session.commit()
    ps1 = patches.render_patch_manifest(session, patch_set.id)
    h1 = ps1.content_hash
    ps2 = patches.render_patch_manifest(session, patch_set.id)
    assert ps2.content_hash == h1


def test_render_changes_after_patch_add(session, patch_set):
    ps1 = patches.render_patch_manifest(session, patch_set.id)
    h1 = ps1.content_hash
    patches.add_patch(session, patch_set.id, 10, "new.patch")
    session.commit()
    ps2 = patches.render_patch_manifest(session, patch_set.id)
    assert ps2.content_hash != h1
