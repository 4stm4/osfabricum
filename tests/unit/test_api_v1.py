"""Tests for M20: API + Web UI v1 (catalog/artifacts/workers/plan, SSE, dashboard)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Artifact,
    Base,
    Board,
    Distribution,
    Package,
    PackageVersion,
    Profile,
    Worker,
)
from osfabricum.db.session import sync_session
from osfabricum.settings import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


@pytest.fixture()
def seeded(db_url: str) -> dict:
    """Populate registry + a few artifacts/workers."""
    with sync_session(db_url) as session:
        arch = Architecture(name="aarch64")
        session.add(arch)
        session.flush()
        board = Board(
            name="rpi-zero-2w",
            arch_id=arch.id,
            boot_scheme="uboot",
            firmware_required=True,
        )
        session.add(board)
        session.flush()
        dist = Distribution(name="tinywifi", description="Wi-Fi AP OS", default_channel="dev")
        session.add(dist)
        session.flush()
        prof = Profile(distribution_id=dist.id, name="default")
        session.add(prof)
        session.flush()
        pkg = Package(name="nanodhcp", package_type="native")
        session.add(pkg)
        session.flush()
        pv = PackageVersion(
            package_id=pkg.id,
            version="0.1.0",
            arch_id=arch.id,
            status="built",
        )
        session.add(pv)
        art = Artifact(
            kind="image",
            name="tinywifi-default-rpi-zero-2w",
            arch="aarch64",
            store_key="images/tinywifi/x",
            blob_sha256="a" * 64,
            size_bytes=1048576,
            media_type="application/gzip",
            retention_class="staging",
        )
        session.add(art)
        worker = Worker(
            hostname="worker-01",
            enabled=True,
            kinds_json=["kernel.build", "package.build"],
            tags_json=["arch:aarch64"],
            last_seen_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(worker)
        session.commit()
        return {
            "arch_id": arch.id,
            "board_id": board.id,
            "dist_id": dist.id,
            "profile_id": prof.id,
            "artifact_id": art.id,
        }


# ---------------------------------------------------------------------------
# Catalog API
# ---------------------------------------------------------------------------


def test_catalog_distributions(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/catalog/distributions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "tinywifi"
    assert data[0]["description"] == "Wi-Fi AP OS"


def test_catalog_boards(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/catalog/boards")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "rpi-zero-2w"
    assert data[0]["arch"] == "aarch64"
    assert data[0]["firmware_required"] is True


def test_catalog_boards_filter_arch(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/catalog/boards?arch=aarch64")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    resp2 = client.get("/v1/catalog/boards?arch=x86_64")
    assert resp2.status_code == 200
    assert resp2.json() == []


def test_catalog_packages(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/catalog/packages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "nanodhcp"
    assert data[0]["versions"][0]["version"] == "0.1.0"
    assert data[0]["versions"][0]["status"] == "built"


def test_catalog_packages_name_filter(client: TestClient, seeded: dict) -> None:
    assert len(client.get("/v1/catalog/packages?name=nano").json()) == 1
    assert client.get("/v1/catalog/packages?name=zzz").json() == []


# ---------------------------------------------------------------------------
# Artifacts API
# ---------------------------------------------------------------------------


def test_artifacts_search_all(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/artifacts")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_artifacts_filter_kind(client: TestClient, seeded: dict) -> None:
    assert len(client.get("/v1/artifacts?kind=image").json()) == 1
    assert client.get("/v1/artifacts?kind=kernel").json() == []


def test_artifacts_filter_arch(client: TestClient, seeded: dict) -> None:
    assert len(client.get("/v1/artifacts?arch=aarch64").json()) == 1


def test_artifacts_get_by_id(client: TestClient, seeded: dict) -> None:
    aid = seeded["artifact_id"]
    resp = client.get(f"/v1/artifacts/{aid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == aid
    assert data["kind"] == "image"
    assert data["size_bytes"] == 1048576


def test_artifacts_get_not_found(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/artifacts/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Workers API
# ---------------------------------------------------------------------------


def test_workers_list(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/workers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["hostname"] == "worker-01"
    assert "kernel.build" in data[0]["kinds"]


def test_workers_get_by_hostname(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/workers/worker-01")
    assert resp.status_code == 200
    assert resp.json()["hostname"] == "worker-01"


def test_workers_get_not_found(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/workers/no-such-worker")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Plan API
# ---------------------------------------------------------------------------


def test_plan_resolve(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/plan?distribution=tinywifi&profile=default&board=rpi-zero-2w")
    assert resp.status_code == 200
    data = resp.json()
    assert data["distribution"] == "tinywifi"
    assert data["board"] == "rpi-zero-2w"
    assert data["arch"] == "aarch64"
    assert "resolution_hash" in data


def test_plan_unknown_distribution(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/plan?distribution=missing&profile=default&board=rpi-zero-2w")
    assert resp.status_code == 404


def test_plan_missing_query_param(client: TestClient, seeded: dict) -> None:
    # No board → 422 validation error
    resp = client.get("/v1/plan?distribution=tinywifi&profile=default")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# SSE events stream
# ---------------------------------------------------------------------------


def test_build_events_stream(client: TestClient, db_url: str, seeded: dict) -> None:
    """SSE stream emits existing events and ends on terminal status."""
    from osfabricum.pipeline.record import (
        create_build,
        log_build_event,
        update_build_status,
    )

    bid = create_build(
        seeded["dist_id"],
        seeded["profile_id"],
        seeded["board_id"],
        "sha256:" + "a" * 64,
        db_url=db_url,
    )
    log_build_event(bid, "build.start", {}, db_url=db_url)
    log_build_event(bid, "step.done", {"step": "rootfs.base"}, db_url=db_url)
    # Build is already terminal so the stream returns promptly
    update_build_status(bid, "success", db_url=db_url)

    resp = client.get(f"/v1/builds/{bid}/events/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "build.start" in body
    assert "event: end" in body


def test_build_events_stream_not_found(client: TestClient, seeded: dict) -> None:
    resp = client.get("/v1/builds/00000000-0000-0000-0000-000000000000/events/stream")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Web UI dashboard
# ---------------------------------------------------------------------------


def test_dashboard_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "OSFabricum" in resp.text


def test_dashboard_has_tabs(client: TestClient) -> None:
    resp = client.get("/")
    body = resp.text
    for tab in ["builds", "artifacts", "distributions", "boards", "workers"]:
        assert f'data-tab="{tab}"' in body


def test_static_assets_mounted(client: TestClient) -> None:
    # index.html is also reachable via /static
    resp = client.get("/static/index.html")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_openapi_includes_v1_routes(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/v1/catalog/distributions" in paths
    assert "/v1/artifacts" in paths
    assert "/v1/workers" in paths
    assert "/v1/plan" in paths
    assert "/v1/builds" in paths


# ---------------------------------------------------------------------------
# Auth interaction (dashboard + static stay public when auth enabled)
# ---------------------------------------------------------------------------


def test_dashboard_public_with_auth_enabled(db_url: str) -> None:
    import os

    from osfabricum.settings import AuthSettings

    settings = Settings()
    settings.database.url = db_url
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = "secret"
    c = TestClient(create_app(settings))
    # Dashboard root is public
    assert c.get("/").status_code == 200
    # Static asset is public
    assert c.get("/static/index.html").status_code == 200
    # v1 reads stay public (G-24: only writes and admin endpoints need a token)
    assert c.get("/v1/catalog/distributions").status_code in (200, 500)
    os.environ.pop("OSFABRICUM_API_TOKEN", None)
