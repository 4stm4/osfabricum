"""Tests for the M28 Build Wizard: drafts + the draft→plan→build flow."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from osfabricum import orchestrator
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Base, Board, Distribution, Profile
from osfabricum.db.session import sync_session
from osfabricum.settings import Settings


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'm28.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    from pyjobkit.backends.sql.schema import metadata as pjk_meta

    pjk_meta.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        s.add(Board(name="rpi", arch_id=arch.id, boot_scheme="direct-kernel"))
        dist = Distribution(name="edge-os")
        s.add(dist)
        s.flush()
        s.add(Profile(distribution_id=dist.id, name="default"))
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


def test_draft_service_crud(db_url: str) -> None:
    draft = orchestrator.create_draft(
        name="my draft", distribution="edge-os", profile="default", board="rpi", db_url=db_url
    )
    assert draft["status"] == "draft"
    got = orchestrator.get_draft(draft["id"], db_url=db_url)
    assert got["distribution"] == "edge-os"

    orchestrator.update_draft(draft["id"], overrides={"package_set": "core"}, db_url=db_url)
    assert orchestrator.get_draft(draft["id"], db_url=db_url)["overrides"] == {
        "package_set": "core"
    }

    assert len(orchestrator.list_drafts(db_url=db_url)) == 1
    orchestrator.delete_draft(draft["id"], db_url=db_url)
    assert orchestrator.list_drafts(db_url=db_url) == []


def test_draft_api_crud(client: TestClient) -> None:
    r = client.post("/v1/build-drafts", json={"name": "d1", "distribution": "edge-os"})
    assert r.status_code == 201
    draft_id = r.json()["id"]

    assert client.get("/v1/build-drafts").json()[0]["id"] == draft_id
    assert client.get(f"/v1/build-drafts/{draft_id}").json()["name"] == "d1"

    upd = client.patch(f"/v1/build-drafts/{draft_id}", json={"profile": "default", "board": "rpi"})
    assert upd.json()["profile"] == "default"

    assert client.delete(f"/v1/build-drafts/{draft_id}").status_code == 204
    assert client.get(f"/v1/build-drafts/{draft_id}").status_code == 404


def test_wizard_flow_draft_plan_build(client: TestClient) -> None:
    # 1. save a draft
    draft = client.post(
        "/v1/build-drafts",
        json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
    ).json()

    # 2. preview the plan (no build)
    plan = client.post(
        "/v1/plan",
        json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
    )
    assert plan.status_code == 200
    assert plan.json()["arch"] == "aarch64"

    # 3. build
    out = client.post(
        "/v1/builds",
        json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
    )
    assert out.status_code == 201
    assert out.json()["status"] == "queued"

    # 4. mark the draft built
    client.patch(f"/v1/build-drafts/{draft['id']}", json={"status": "built"})
    assert client.get(f"/v1/build-drafts/{draft['id']}").json()["status"] == "built"
