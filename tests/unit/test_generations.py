"""Unit tests for M60 — System Generations / Rollback Designer."""

from __future__ import annotations

import pytest

from osfabricum import generations as gen_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_rollback_kinds

DIST_ID = "dist-uuid-0001"


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_generations.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_rollback_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def gen(session):
    g = gen_svc.create_generation(
        session, distribution_id=DIST_ID, generation_number=1,
        description="First release",
    )
    session.commit()
    return g


# ---------------------------------------------------------------------------
# Rollback kinds
# ---------------------------------------------------------------------------


def test_rollback_kinds_seeded(session):
    kinds = gen_svc.list_rollback_kinds(session)
    assert len(kinds) == 4


def test_rollback_kinds_ordered(session):
    kinds = gen_svc.list_rollback_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_rollback_kinds_valid_set(session):
    kinds = gen_svc.list_rollback_kinds(session)
    assert {k.kind for k in kinds} == gen_svc.VALID_ROLLBACK_KINDS


# ---------------------------------------------------------------------------
# create_generation
# ---------------------------------------------------------------------------


def test_create_generation_basic(session, gen):
    assert gen.id is not None
    assert gen.generation_number == 1
    assert gen.status == "active"
    assert gen.distribution_id == DIST_ID


def test_create_generation_defaults(session, gen):
    assert gen.content_hash is None
    assert gen.rendered_at is None
    assert gen.rendered_generation_manifest is None


def test_create_generation_custom_status(session):
    g = gen_svc.create_generation(session, DIST_ID, 99, status="archived")
    assert g.status == "archived"


def test_create_generation_invalid_status(session):
    with pytest.raises(ValueError, match="Invalid status"):
        gen_svc.create_generation(session, DIST_ID, 2, status="pending")


def test_create_generation_all_statuses(session):
    for i, st in enumerate(sorted(gen_svc.VALID_STATUSES)):
        g = gen_svc.create_generation(session, DIST_ID, 100 + i, status=st)
        assert g.status == st


# ---------------------------------------------------------------------------
# get / list / update
# ---------------------------------------------------------------------------


def test_get_generation(session, gen):
    fetched = gen_svc.get_generation(session, gen.id)
    assert fetched.id == gen.id


def test_get_generation_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        gen_svc.get_generation(session, "no-such-uuid")


def test_list_generations_empty(session):
    assert gen_svc.list_generations(session) == []


def test_list_generations_returns_all(session, gen):
    gen_svc.create_generation(session, DIST_ID, 2)
    gens = gen_svc.list_generations(session)
    assert len(gens) == 2


def test_list_generations_ordered_desc(session):
    gen_svc.create_generation(session, DIST_ID, 1)
    gen_svc.create_generation(session, DIST_ID, 3)
    gen_svc.create_generation(session, DIST_ID, 2)
    gens = gen_svc.list_generations(session)
    nums = [g.generation_number for g in gens]
    assert nums == sorted(nums, reverse=True)


def test_list_generations_filter_by_dist(session):
    gen_svc.create_generation(session, "dist-a", 1)
    gen_svc.create_generation(session, "dist-b", 1)
    filtered = gen_svc.list_generations(session, distribution_id="dist-a")
    assert len(filtered) == 1 and filtered[0].distribution_id == "dist-a"


def test_list_generations_filter_by_status(session):
    gen_svc.create_generation(session, DIST_ID, 1, status="active")
    gen_svc.create_generation(session, DIST_ID, 2, status="archived")
    active = gen_svc.list_generations(session, status="active")
    assert len(active) == 1 and active[0].status == "active"


def test_update_generation_status(session, gen):
    updated = gen_svc.update_generation(session, gen.id, status="archived")
    assert updated.status == "archived"


def test_update_generation_description(session, gen):
    updated = gen_svc.update_generation(session, gen.id, description="Updated desc")
    assert updated.description == "Updated desc"


def test_update_generation_invalidates_hash(session, gen):
    gen_svc.render_generation_manifest(session, gen.id)
    session.refresh(gen)
    gen_svc.update_generation(session, gen.id, status="archived")
    session.refresh(gen)
    assert gen.content_hash is None


def test_update_generation_invalid_status(session, gen):
    with pytest.raises(ValueError, match="Invalid status"):
        gen_svc.update_generation(session, gen.id, status="broken")


def test_update_generation_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        gen_svc.update_generation(session, "no-such", status="archived")


# ---------------------------------------------------------------------------
# add_generation_artifact
# ---------------------------------------------------------------------------


def test_add_artifact_basic(session, gen):
    a = gen_svc.add_generation_artifact(
        session, gen.id, artifact_role="image",
        artifact_uri="s3://bucket/image.ext4.gz",
    )
    assert a.artifact_role == "image"
    assert a.artifact_uri == "s3://bucket/image.ext4.gz"


def test_add_artifact_invalid_role(session, gen):
    with pytest.raises(ValueError, match="Invalid artifact_role"):
        gen_svc.add_generation_artifact(session, gen.id, artifact_role="invalid")


def test_add_artifact_all_roles(session, gen):
    for role in sorted(gen_svc.VALID_ARTIFACT_ROLES):
        a = gen_svc.add_generation_artifact(session, gen.id, artifact_role=role)
        assert a.artifact_role == role


def test_add_artifact_upsert(session, gen):
    a1 = gen_svc.add_generation_artifact(
        session, gen.id, artifact_role="kernel", artifact_uri="old-uri"
    )
    a2 = gen_svc.add_generation_artifact(
        session, gen.id, artifact_role="kernel", artifact_uri="new-uri"
    )
    assert a1.id == a2.id
    assert a2.artifact_uri == "new-uri"


def test_add_artifact_invalidates_manifest(session, gen):
    gen_svc.render_generation_manifest(session, gen.id)
    session.refresh(gen)
    assert gen.content_hash is not None
    gen_svc.add_generation_artifact(session, gen.id, artifact_role="image")
    session.refresh(gen)
    assert gen.content_hash is None


# ---------------------------------------------------------------------------
# add_rollback_target
# ---------------------------------------------------------------------------


def test_add_rollback_target_basic(session, gen):
    t = gen_svc.add_rollback_target(
        session, gen.id, target_generation_number=0, rollback_kind="full"
    )
    assert t.target_generation_number == 0
    assert t.rollback_kind == "full"


def test_add_rollback_target_invalid_kind(session, gen):
    with pytest.raises(ValueError, match="Invalid rollback_kind"):
        gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="bad")


def test_add_rollback_target_all_kinds(session, gen):
    for i, k in enumerate(sorted(gen_svc.VALID_ROLLBACK_KINDS)):
        t = gen_svc.add_rollback_target(session, gen.id, i, rollback_kind=k)
        assert t.rollback_kind == k


def test_add_rollback_target_upsert(session, gen):
    t1 = gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="full")
    t2 = gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="config-only")
    assert t1.id == t2.id
    assert t2.rollback_kind == "config-only"


# ---------------------------------------------------------------------------
# render_generation_manifest
# ---------------------------------------------------------------------------


def test_render_manifest_basic(session, gen):
    g = gen_svc.render_generation_manifest(session, gen.id)
    assert g.rendered_generation_manifest is not None
    assert g.content_hash is not None
    assert g.content_hash.startswith("sha256:")


def test_render_manifest_contains_generation_num(session, gen):
    g = gen_svc.render_generation_manifest(session, gen.id)
    assert str(gen.generation_number) in g.rendered_generation_manifest


def test_render_manifest_contains_status(session, gen):
    g = gen_svc.render_generation_manifest(session, gen.id)
    assert "active" in g.rendered_generation_manifest


def test_render_manifest_contains_artifacts(session, gen):
    gen_svc.add_generation_artifact(session, gen.id, artifact_role="image",
                                     artifact_uri="s3://b/img.gz")
    g = gen_svc.render_generation_manifest(session, gen.id)
    assert "image" in g.rendered_generation_manifest
    assert "s3://b/img.gz" in g.rendered_generation_manifest


def test_render_manifest_contains_rollback_targets(session, gen):
    gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="full")
    g = gen_svc.render_generation_manifest(session, gen.id)
    assert "rollback_targets" in g.rendered_generation_manifest


def test_render_manifest_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        gen_svc.render_generation_manifest(session, "no-such")


# ---------------------------------------------------------------------------
# render_rollback_plan
# ---------------------------------------------------------------------------


def test_render_rollback_plan_full(session, gen):
    gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="full")
    t = gen_svc.render_rollback_plan(session, gen.id, 0)
    assert "full" in t.rendered_rollback_plan
    assert "rootfs" in t.rendered_rollback_plan


def test_render_rollback_plan_config_only(session, gen):
    gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="config-only")
    t = gen_svc.render_rollback_plan(session, gen.id, 0)
    assert "config" in t.rendered_rollback_plan


def test_render_rollback_plan_data_preserve(session, gen):
    gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="data-preserve")
    t = gen_svc.render_rollback_plan(session, gen.id, 0)
    assert "data partition" in t.rendered_rollback_plan


def test_render_rollback_plan_partial(session, gen):
    gen_svc.add_rollback_target(session, gen.id, 0, rollback_kind="partial")
    t = gen_svc.render_rollback_plan(session, gen.id, 0)
    assert "partial" in t.rendered_rollback_plan


def test_render_rollback_plan_not_found_raises(session, gen):
    with pytest.raises(KeyError, match="not found"):
        gen_svc.render_rollback_plan(session, gen.id, 999)


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_render_manifest_deterministic(session):
    g = gen_svc.create_generation(session, DIST_ID, 10)
    h1 = gen_svc.render_generation_manifest(session, g.id).content_hash
    h2 = gen_svc.render_generation_manifest(session, g.id).content_hash
    assert h1 == h2
