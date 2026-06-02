"""Tests for the Universal OS Builder Model (M25).

A distribution + profile of *every* class can be created and resolved, with no
dependence on a reference distribution; the universal entities are referenceable
from a profile; the fixed enumerations seed idempotently; and the
class read surfaces (API + CLI) work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from apps.api.app import create_app
from apps.cli.main import app as cli_app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Base,
    Board,
    BootScheme,
    BrandingProfile,
    Distribution,
    DistributionClass,
    GraphicalProfile,
    ImageRecipe,
    NetworkProfile,
    PackageSet,
    Profile,
    SecurityProfile,
    UpdateStrategy,
    ValidationProfile,
)
from osfabricum.db.seed_data import (
    BOOT_SCHEMES,
    DISTRIBUTION_CLASSES,
    seed_boot_schemes,
    seed_distribution_classes,
)
from osfabricum.db.session import sync_session
from osfabricum.resolver import resolve_plan
from osfabricum.settings import Settings

runner = CliRunner()

CLASS_NAMES = [name for name, _ in DISTRIBUTION_CLASSES]


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'm25.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        seed_distribution_classes(s)
        seed_boot_schemes(s)
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


def test_seed_contents(db_url: str) -> None:
    with sync_session(db_url) as s:
        classes = {c.name for c in s.scalars(select(DistributionClass)).all()}
        schemes = {b.name for b in s.scalars(select(BootScheme)).all()}
    assert classes == set(CLASS_NAMES)
    assert len(classes) == 11
    assert schemes == {name for name, _ in BOOT_SCHEMES}


def test_seed_is_idempotent(db_url: str) -> None:
    with sync_session(db_url) as s:
        added_classes = seed_distribution_classes(s)
        added_schemes = seed_boot_schemes(s)
        s.commit()
    assert added_classes == 0
    assert added_schemes == 0


@pytest.mark.parametrize("class_name", CLASS_NAMES)
def test_create_and_resolve_for_each_class(db_url: str, class_name: str) -> None:
    """Every distribution class can be created and resolved as pure data."""
    with sync_session(db_url) as s:
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        board = Board(name=f"board-{class_name}", arch_id=arch.id, boot_scheme="direct-kernel")
        s.add(board)
        s.flush()
        cls = s.scalar(select(DistributionClass).where(DistributionClass.name == class_name))
        assert cls is not None
        dist = Distribution(name=f"os-{class_name}", class_id=cls.id)
        s.add(dist)
        s.flush()
        s.add(Profile(distribution_id=dist.id, name="default", class_id=cls.id, board_id=board.id))
        s.commit()
        dist_name, board_name = dist.name, board.name

    plan = resolve_plan(dist_name, "default", board_name, db_url=db_url)
    assert plan.resolution_hash.startswith("sha256:")
    assert plan.arch == "aarch64"
    assert plan.distribution == dist_name


def test_profile_references_universal_entities(db_url: str) -> None:
    with sync_session(db_url) as s:
        dist = Distribution(name="os-universal")
        s.add(dist)
        s.flush()
        ps = PackageSet(name="core", distribution_id=dist.id)
        br = BrandingProfile(name="brand", distribution_id=dist.id)
        gp = GraphicalProfile(name="shell", distribution_id=dist.id, mode="kiosk")
        net = NetworkProfile(name="net", distribution_id=dist.id)
        sec = SecurityProfile(name="hardened", distribution_id=dist.id)
        img = ImageRecipe(name="img", distribution_id=dist.id, output_format="qcow2")
        upd = UpdateStrategy(name="ab", distribution_id=dist.id, strategy="ab")
        val = ValidationProfile(name="qa", distribution_id=dist.id)
        for obj in (ps, br, gp, net, sec, img, upd, val):
            s.add(obj)
        s.flush()
        boot = s.scalar(select(BootScheme).where(BootScheme.name == "u-boot"))
        prof = Profile(
            distribution_id=dist.id,
            name="full",
            package_set_id=ps.id,
            branding_profile_id=br.id,
            graphical_profile_id=gp.id,
            network_profile_id=net.id,
            security_profile_id=sec.id,
            image_recipe_id=img.id,
            update_strategy_id=upd.id,
            validation_profile_id=val.id,
            boot_scheme_id=boot.id,
        )
        s.add(prof)
        s.commit()
        pid = prof.id

    with sync_session(db_url) as s:
        p = s.scalar(select(Profile).where(Profile.id == pid))
        assert p is not None
        assert s.scalar(select(PackageSet).where(PackageSet.id == p.package_set_id)) is not None
        graphical = s.scalar(
            select(GraphicalProfile).where(GraphicalProfile.id == p.graphical_profile_id)
        )
        assert graphical is not None and graphical.mode == "kiosk"
        recipe = s.scalar(select(ImageRecipe).where(ImageRecipe.id == p.image_recipe_id))
        assert recipe is not None and recipe.output_format == "qcow2"
        assert p.boot_scheme_id is not None


def test_package_group_reusable_across_distributions(db_url: str) -> None:
    """A global (distribution_id=NULL) package set is shared across distributions."""
    with sync_session(db_url) as s:
        shared = PackageSet(name="shared-core", distribution_id=None)
        s.add(shared)
        s.flush()
        d1 = Distribution(name="os-one")
        d2 = Distribution(name="os-two")
        s.add_all([d1, d2])
        s.flush()
        s.add(Profile(distribution_id=d1.id, name="p", package_set_id=shared.id))
        s.add(Profile(distribution_id=d2.id, name="p", package_set_id=shared.id))
        s.commit()
        users = s.scalars(select(Profile).where(Profile.package_set_id == shared.id)).all()
    assert len(users) == 2


def test_api_distribution_classes(client: TestClient) -> None:
    resp = client.get("/v1/distribution-classes")
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert names == set(CLASS_NAMES)
    assert "hypervisor-host" in names


def test_cli_list_distribution_classes(db_url: str) -> None:
    result = runner.invoke(cli_app, ["catalog", "list", "distribution-classes", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "router" in result.output
    assert "hypervisor-host" in result.output
