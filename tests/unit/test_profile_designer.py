"""Tests for the Profile Designer (M27): service + resolver wiring + API + CLI.

The headline test is ``test_two_profiles_resolve_to_two_package_sets`` — the
acceptance for G-02: the resolver now consumes the profile, so two profiles of
the same distribution/arch with different package sets resolve to different
packages (and different resolution hashes).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from apps.api.app import create_app
from apps.cli.main import app as cli_app
from osfabricum import profile as svc
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Base,
    Board,
    Distribution,
    Package,
    PackageSet,
    PackageSetMember,
    PackageVersion,
)
from osfabricum.db.seed_data import seed_boot_schemes, seed_distribution_classes
from osfabricum.db.session import sync_session
from osfabricum.resolver import resolve_plan
from osfabricum.settings import Settings

runner = CliRunner()


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'm27.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        seed_distribution_classes(s)
        seed_boot_schemes(s)
        s.add(Distribution(name="edge-os"))
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


def _make_package_set(s, dist_id: str, set_name: str, pkg_name: str, arch_id: str) -> None:
    pkg = Package(name=pkg_name, package_type="native")
    s.add(pkg)
    s.flush()
    s.add(PackageVersion(package_id=pkg.id, version="1.0.0", arch_id=arch_id, status="pending"))
    pset = PackageSet(name=set_name, distribution_id=dist_id)
    s.add(pset)
    s.flush()
    s.add(PackageSetMember(set_id=pset.id, member_kind="package", package_id=pkg.id))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_create_get_list(db_url: str) -> None:
    svc.create_profile(
        distribution="edge-os", name="default", refs={"class": "router"}, db_url=db_url
    )
    got = svc.get_profile("edge-os", "default", db_url=db_url)
    assert got["name"] == "default"
    assert got["class"] == "router"
    assert [p["name"] for p in svc.list_profiles("edge-os", db_url=db_url)] == ["default"]


def test_create_unknown_ref_and_duplicate(db_url: str) -> None:
    with pytest.raises(ValueError, match="unknown class"):
        svc.create_profile(distribution="edge-os", name="x", refs={"class": "ghost"}, db_url=db_url)
    svc.create_profile(distribution="edge-os", name="dup", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        svc.create_profile(distribution="edge-os", name="dup", db_url=db_url)


def test_inheritance_and_update(db_url: str) -> None:
    svc.create_profile(distribution="edge-os", name="base", inputs={"k": "v"}, db_url=db_url)
    child = svc.create_profile(distribution="edge-os", name="child", inherits="base", db_url=db_url)
    assert child["inherits"] == "base"
    out = svc.update_profile("edge-os", "child", inputs={"k": "child"}, db_url=db_url)
    assert out["inputs"] == {"k": "child"}


def test_clone(db_url: str) -> None:
    svc.create_profile(distribution="edge-os", name="src", refs={"class": "kiosk"}, db_url=db_url)
    clone = svc.clone_profile("edge-os", "src", "dst", db_url=db_url)
    assert clone["name"] == "dst"
    assert clone["class"] == "kiosk"


def test_versioning(db_url: str) -> None:
    svc.create_profile(distribution="edge-os", name="v", db_url=db_url)
    assert svc.create_version("edge-os", "v", db_url=db_url)["version"] == 1
    svc.update_profile("edge-os", "v", refs={"class": "server"}, db_url=db_url)
    assert svc.create_version("edge-os", "v", db_url=db_url)["version"] == 2
    versions = svc.list_versions("edge-os", "v", db_url=db_url)
    assert [r["version"] for r in versions] == [1, 2]
    assert versions[1]["snapshot"]["class"] == "server"


def test_diff(db_url: str) -> None:
    svc.create_profile(distribution="edge-os", name="a", refs={"class": "router"}, db_url=db_url)
    svc.create_profile(distribution="edge-os", name="b", refs={"class": "server"}, db_url=db_url)
    diff = svc.diff_profiles("edge-os", "a", "b", db_url=db_url)
    assert diff["changes"]["class"] == {"a": "router", "b": "server"}


def test_export_import_roundtrip(db_url: str) -> None:
    svc.create_profile(
        distribution="edge-os",
        name="full",
        refs={"class": "appliance", "boot_scheme": "u-boot"},
        inputs={"hostname": "edge"},
        db_url=db_url,
    )
    doc = svc.export_profile("edge-os", "full", db_url=db_url)
    assert doc["kind"] == "Profile"
    assert doc["spec"]["class"] == "appliance"
    assert doc["spec"]["boot_scheme"] == "u-boot"
    # re-import under a new name
    doc["metadata"]["name"] = "full-copy"
    out = svc.import_profile(doc, db_url=db_url)
    assert out["class"] == "appliance"
    assert out["inputs"] == {"hostname": "edge"}


def test_delete_refused_when_inherited(db_url: str) -> None:
    svc.create_profile(distribution="edge-os", name="parent", db_url=db_url)
    svc.create_profile(distribution="edge-os", name="kid", inherits="parent", db_url=db_url)
    with pytest.raises(ValueError, match="inherited by"):
        svc.delete_profile("edge-os", "parent", db_url=db_url)
    svc.delete_profile("edge-os", "kid", db_url=db_url)
    svc.delete_profile("edge-os", "parent", db_url=db_url)


# ---------------------------------------------------------------------------
# Resolver wiring (G-02) — the acceptance test
# ---------------------------------------------------------------------------


def test_two_profiles_resolve_to_two_package_sets(db_url: str) -> None:
    with sync_session(db_url) as s:
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        s.add(Board(name="rpi", arch_id=arch.id, boot_scheme="direct-kernel"))
        dist = s.scalar(select(Distribution).where(Distribution.name == "edge-os"))
        _make_package_set(s, dist.id, "set-a", "pkg-a", arch.id)
        _make_package_set(s, dist.id, "set-b", "pkg-b", arch.id)
        s.commit()

    svc.create_profile(
        distribution="edge-os", name="prof-a", refs={"package_set": "set-a"}, db_url=db_url
    )
    svc.create_profile(
        distribution="edge-os", name="prof-b", refs={"package_set": "set-b"}, db_url=db_url
    )

    plan_a = resolve_plan("edge-os", "prof-a", "rpi", db_url=db_url)
    plan_b = resolve_plan("edge-os", "prof-b", "rpi", db_url=db_url)

    assert {p.name for p in plan_a.packages} == {"pkg-a"}
    assert {p.name for p in plan_b.packages} == {"pkg-b"}
    assert plan_a.resolution_hash != plan_b.resolution_hash


def test_profile_inputs_packages_drive_selection(db_url: str) -> None:
    with sync_session(db_url) as s:
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        s.add(Board(name="rpi", arch_id=arch.id, boot_scheme="direct-kernel"))
        for name in ("keep-me", "ignore-me"):
            pkg = Package(name=name, package_type="native")
            s.add(pkg)
            s.flush()
            s.add(
                PackageVersion(package_id=pkg.id, version="1.0", arch_id=arch.id, status="pending")
            )
        s.commit()

    svc.create_profile(
        distribution="edge-os", name="picky", inputs={"packages": ["keep-me"]}, db_url=db_url
    )
    plan = resolve_plan("edge-os", "picky", "rpi", db_url=db_url)
    assert {p.name for p in plan.packages} == {"keep-me"}


# ---------------------------------------------------------------------------
# API + CLI
# ---------------------------------------------------------------------------


def test_api_crud_clone_version_diff(client: TestClient) -> None:
    r = client.post(
        "/v1/profiles",
        json={"distribution": "edge-os", "name": "p1", "refs": {"class": "router"}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["class"] == "router"

    assert client.get("/v1/profiles?distribution=edge-os").json()[0]["name"] == "p1"
    assert client.get("/v1/profiles/edge-os/p1").json()["name"] == "p1"

    assert (
        client.patch("/v1/profiles/edge-os/p1", json={"refs": {"class": "server"}}).json()["class"]
        == "server"
    )
    assert client.post("/v1/profiles/edge-os/p1/clone", json={"name": "p2"}).status_code == 201
    assert client.post("/v1/profiles/edge-os/p1/versions").json()["version"] == 1
    assert client.get("/v1/profiles/edge-os/p1/versions").json()[0]["version"] == 1

    diff = client.post("/v1/profiles/edge-os/diff", json={"a": "p1", "b": "p2"}).json()
    assert "changes" in diff

    assert client.delete("/v1/profiles/edge-os/p2").status_code == 204
    assert client.get("/v1/profiles/edge-os/missing").status_code == 404


def test_api_import_export(client: TestClient) -> None:
    doc = {
        "apiVersion": "osfabricum/v1",
        "kind": "Profile",
        "metadata": {"distribution": "edge-os", "name": "imported"},
        "spec": {"class": "desktop", "inputs": {"x": 1}},
    }
    assert client.post("/v1/profiles/import", json=doc).status_code == 201
    out = client.get("/v1/profiles/edge-os/imported/export").json()
    assert out["spec"]["class"] == "desktop"
    assert client.post("/v1/profiles/import", json={"kind": "Nope"}).status_code == 400


def test_cli_create_list_clone_export(db_url: str, tmp_path: Path) -> None:
    res = runner.invoke(
        cli_app,
        ["profile", "create", "edge-os", "cliprof", "--set", "class=router", "--db-url", db_url],
    )
    assert res.exit_code == 0, res.output
    res = runner.invoke(cli_app, ["profile", "list", "edge-os", "--db-url", db_url])
    assert "cliprof" in res.output
    res = runner.invoke(
        cli_app, ["profile", "clone", "edge-os", "cliprof", "cliprof2", "--db-url", db_url]
    )
    assert res.exit_code == 0, res.output
    out = tmp_path / "p.yaml"
    res = runner.invoke(
        cli_app, ["profile", "export", "edge-os", "cliprof", "--file", str(out), "--db-url", db_url]
    )
    assert res.exit_code == 0
    assert yaml.safe_load(out.read_text())["spec"]["class"] == "router"
