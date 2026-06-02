"""Tests for the Distribution Designer (M26): service + API + CLI.

Covers create/clone/import/export round-trips, validation (imports are not
trusted blindly), class assignment, and — critically — that reference
distributions carry no special code path: a distribution named "tinywifi" is
created, cloned, and exported exactly like any other.
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
from osfabricum import distribution as svc
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Base, Board, Build, Distribution, Profile
from osfabricum.db.seed_data import seed_distribution_classes
from osfabricum.db.session import sync_session
from osfabricum.settings import Settings

runner = CliRunner()

DOC = {
    "apiVersion": "osfabricum/v1",
    "kind": "Distribution",
    "metadata": {
        "name": "edge-os",
        "description": "edge appliance",
        "default_channel": "stable",
        "class": "appliance",
    },
    "profiles": [
        {"name": "base", "inputs": {"arch": "aarch64"}},
        {"name": "default", "inherits": "base", "inputs": {"hostname": "edge"}},
    ],
}


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'm26.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        seed_distribution_classes(s)
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_create_get_list(db_url: str) -> None:
    svc.create_distribution(name="alpha", description="a", class_name="router", db_url=db_url)
    got = svc.get_distribution("alpha", db_url=db_url)
    assert got["name"] == "alpha"
    assert got["class"] == "router"
    rows = svc.list_distributions(db_url=db_url)
    assert [r["name"] for r in rows] == ["alpha"]
    assert rows[0]["profile_count"] == 0


def test_create_duplicate_and_unknown_class(db_url: str) -> None:
    svc.create_distribution(name="dup", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        svc.create_distribution(name="dup", db_url=db_url)
    with pytest.raises(ValueError, match="unknown distribution class"):
        svc.create_distribution(name="bad", class_name="not-a-class", db_url=db_url)


def test_update(db_url: str) -> None:
    svc.create_distribution(name="up", default_channel="dev", db_url=db_url)
    out = svc.update_distribution(
        "up", default_channel="stable", class_name="server", db_url=db_url
    )
    assert out["default_channel"] == "stable"
    assert out["class"] == "server"


def test_delete_refused_with_builds(db_url: str) -> None:
    svc.create_distribution(name="hasbuild", db_url=db_url)
    with sync_session(db_url) as s:
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        board = Board(name="b", arch_id=arch.id, boot_scheme="direct-kernel")
        s.add(board)
        s.flush()
        dist = s.scalar(select(Distribution).where(Distribution.name == "hasbuild"))
        assert dist is not None
        prof = Profile(distribution_id=dist.id, name="default")
        s.add(prof)
        s.flush()
        s.add(Build(distribution_id=dist.id, profile_id=prof.id, board_id=board.id))
        s.commit()
    with pytest.raises(ValueError, match="refusing to delete"):
        svc.delete_distribution("hasbuild", db_url=db_url)


def test_delete_ok(db_url: str) -> None:
    svc.create_distribution(name="gone", db_url=db_url)
    svc.delete_distribution("gone", db_url=db_url)
    assert svc.list_distributions(db_url=db_url) == []


def test_import_creates_profiles_with_inheritance(db_url: str) -> None:
    out = svc.import_distribution(DOC, db_url=db_url)
    assert out["name"] == "edge-os"
    assert out["class"] == "appliance"
    profiles = {p["name"]: p for p in out["profiles"]}
    assert set(profiles) == {"base", "default"}
    assert profiles["default"]["inherits"] == "base"
    assert profiles["default"]["inputs"] == {"hostname": "edge"}


def test_import_validation(db_url: str) -> None:
    with pytest.raises(ValueError, match="invalid distribution document"):
        svc.import_distribution({"kind": "Nope"}, db_url=db_url)
    bad_class = {**DOC, "metadata": {**DOC["metadata"], "name": "x", "class": "ghost"}}
    with pytest.raises(ValueError, match="unknown distribution class"):
        svc.import_distribution(bad_class, db_url=db_url)
    bad_inherit = {
        "apiVersion": "osfabricum/v1",
        "kind": "Distribution",
        "metadata": {"name": "y"},
        "profiles": [{"name": "a", "inherits": "missing"}],
    }
    with pytest.raises(ValueError, match="inherits unknown profile"):
        svc.import_distribution(bad_inherit, db_url=db_url)


def test_export_roundtrip(db_url: str) -> None:
    svc.import_distribution(DOC, db_url=db_url)
    doc = svc.export_distribution("edge-os", db_url=db_url)
    assert doc["apiVersion"] == "osfabricum/v1"
    assert doc["kind"] == "Distribution"
    assert doc["metadata"]["name"] == "edge-os"
    assert doc["metadata"]["class"] == "appliance"
    # Re-import the exported doc under a new name -> equivalent structure.
    doc["metadata"]["name"] = "edge-os-copy"
    out = svc.import_distribution(doc, db_url=db_url)
    assert {p["name"] for p in out["profiles"]} == {"base", "default"}
    assert next(p for p in out["profiles"] if p["name"] == "default")["inherits"] == "base"


def test_clone_copies_profiles_and_remaps_inheritance(db_url: str) -> None:
    svc.import_distribution(DOC, db_url=db_url)
    clone = svc.clone_distribution("edge-os", "edge-os-2", db_url=db_url)
    assert clone["name"] == "edge-os-2"
    assert clone["class"] == "appliance"
    profiles = {p["name"]: p for p in clone["profiles"]}
    assert set(profiles) == {"base", "default"}
    # inheritance points within the clone, by name
    assert profiles["default"]["inherits"] == "base"
    # original is untouched
    assert svc.get_distribution("edge-os", db_url=db_url)["name"] == "edge-os"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_crud_clone(client: TestClient) -> None:
    r = client.post("/v1/distributions", json={"name": "api-os", "class": "kiosk"})
    assert r.status_code == 201, r.text
    assert r.json()["class"] == "kiosk"

    assert client.get("/v1/distributions").json()[0]["name"] == "api-os"
    assert client.get("/v1/distributions/api-os").json()["name"] == "api-os"

    r = client.patch("/v1/distributions/api-os", json={"default_channel": "stable"})
    assert r.json()["default_channel"] == "stable"

    r = client.post("/v1/distributions/api-os/clone", json={"name": "api-os-2"})
    assert r.status_code == 201

    assert client.delete("/v1/distributions/api-os-2").status_code == 204
    assert client.get("/v1/distributions/missing").status_code == 404


def test_api_import_export(client: TestClient) -> None:
    r = client.post("/v1/distributions/import", json=DOC)
    assert r.status_code == 201, r.text
    doc = client.get("/v1/distributions/edge-os/export").json()
    assert doc["metadata"]["name"] == "edge-os"
    assert {p["name"] for p in doc["profiles"]} == {"base", "default"}
    # bad import is rejected (validated, not trusted)
    assert client.post("/v1/distributions/import", json={"kind": "Nope"}).status_code == 400


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_create_list_clone_export_import(db_url: str, tmp_path: Path) -> None:
    res = runner.invoke(
        cli_app, ["distribution", "create", "cli-os", "--class", "desktop", "--db-url", db_url]
    )
    assert res.exit_code == 0, res.output
    assert "cli-os" in res.output

    res = runner.invoke(cli_app, ["distribution", "list", "--db-url", db_url])
    assert "cli-os" in res.output and "desktop" in res.output

    res = runner.invoke(
        cli_app, ["distribution", "clone", "cli-os", "cli-os-2", "--db-url", db_url]
    )
    assert res.exit_code == 0, res.output

    out_file = tmp_path / "export.yaml"
    res = runner.invoke(
        cli_app, ["distribution", "export", "cli-os", "--file", str(out_file), "--db-url", db_url]
    )
    assert res.exit_code == 0
    doc = yaml.safe_load(out_file.read_text())
    assert doc["metadata"]["name"] == "cli-os"

    doc["metadata"]["name"] = "cli-os-imported"
    imp_file = tmp_path / "imp.yaml"
    imp_file.write_text(yaml.safe_dump(doc))
    res = runner.invoke(
        cli_app, ["distribution", "import", "--file", str(imp_file), "--db-url", db_url]
    )
    assert res.exit_code == 0, res.output
    assert "cli-os-imported" in res.output


def test_reference_distribution_is_data_only(db_url: str) -> None:
    """TinyWifi is created/cloned/exported with no special handling."""
    svc.create_distribution(name="tinywifi", class_name="router", db_url=db_url)
    clone = svc.clone_distribution("tinywifi", "tinywifi-fork", db_url=db_url)
    assert clone["name"] == "tinywifi-fork"
    doc = svc.export_distribution("tinywifi", db_url=db_url)
    assert doc["metadata"]["name"] == "tinywifi"
    # nothing distinguishes it from a freshly invented OS
    svc.create_distribution(name="brand-new-os", class_name="router", db_url=db_url)
    a = svc.get_distribution("tinywifi", db_url=db_url)
    b = svc.get_distribution("brand-new-os", db_url=db_url)
    assert a["class"] == b["class"]
