"""Tests for the Build Wizard selector endpoints: /v1/kernels, /v1/package-sets."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Base, Board, Distribution, Kernel, PackageSet
from osfabricum.db.session import sync_session
from osfabricum.settings import Settings


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'sel.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        aarch = Architecture(name="aarch64")
        x86 = Architecture(name="x86_64")
        s.add_all([aarch, x86])
        s.flush()
        s.add(Board(name="rpi-zero-2w", arch_id=aarch.id, boot_scheme="direct-kernel"))
        s.add(Kernel(name="linux-rpi", version="6.6.y", arch_id=aarch.id))
        s.add(Kernel(name="linux-x86", version="6.6", arch_id=x86.id))
        dist = Distribution(name="edge-os")
        s.add(dist)
        s.flush()
        s.add(PackageSet(name="core", distribution_id=dist.id))
        s.add(PackageSet(name="global-set", distribution_id=None))
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


def test_kernels_filtered_by_board(client: TestClient) -> None:
    ks = client.get("/v1/kernels?board=rpi-zero-2w").json()
    assert {k["name"] for k in ks} == {"linux-rpi"}  # x86 kernel excluded
    assert ks[0]["arch"] == "aarch64"
    assert ks[0]["version"] == "6.6.y"


def test_kernels_all_and_by_arch(client: TestClient) -> None:
    assert len(client.get("/v1/kernels").json()) == 2
    assert {k["name"] for k in client.get("/v1/kernels?arch=x86_64").json()} == {"linux-x86"}


def test_package_sets_by_distribution_includes_global(client: TestClient) -> None:
    sets = client.get("/v1/package-sets?distribution=edge-os").json()
    assert {s["name"] for s in sets} == {"core", "global-set"}


def test_package_sets_all(client: TestClient) -> None:
    assert len(client.get("/v1/package-sets").json()) == 2
