"""Tests for the M29 orchestrator: Plan write API + Build API + queue dispatch.

Verifies that the Plan API applies name-based overrides (changing the resolved
packages), that the Build API creates a queued Build and enqueues a ``build.run``
job onto the pyjobkit queue, that a claimed job runs the pipeline for that build,
and that rebuild / clone-as-profile / prefetch behave.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app import create_app
from osfabricum import orchestrator
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Base,
    Board,
    Build,
    Distribution,
    Package,
    PackageSet,
    PackageSetMember,
    PackageVersion,
    Profile,
)
from osfabricum.db.seed_data import seed_distribution_classes
from osfabricum.db.session import sync_session
from osfabricum.queue.backend import JobBackend


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'm29.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    from pyjobkit.backends.sql.schema import metadata as pjk_meta

    pjk_meta.create_all(engine)  # job_tasks table
    engine.dispose()
    with sync_session(url) as s:
        seed_distribution_classes(s)
        arch = Architecture(name="aarch64")
        s.add(arch)
        s.flush()
        s.add(Board(name="rpi", arch_id=arch.id, boot_scheme="direct-kernel"))
        dist = Distribution(name="edge-os")
        s.add(dist)
        s.flush()
        # two package sets with distinct members
        for set_name, pkg_name in (("set-default", "pkg-default"), ("set-x", "pkg-x")):
            pkg = Package(name=pkg_name, package_type="native")
            s.add(pkg)
            s.flush()
            s.add(
                PackageVersion(package_id=pkg.id, version="1.0", arch_id=arch.id, status="pending")
            )
            pset = PackageSet(name=set_name, distribution_id=dist.id)
            s.add(pset)
            s.flush()
            s.add(PackageSetMember(set_id=pset.id, member_kind="package", package_id=pkg.id))
        # a profile that defaults to set-default
        default_set = s.scalar(select(PackageSet).where(PackageSet.name == "set-default"))
        s.add(Profile(distribution_id=dist.id, name="default", package_set_id=default_set.id))
        s.commit()
    return url


@pytest.fixture()
def client(db_url: str) -> TestClient:
    from osfabricum.settings import Settings

    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


def _fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace run_pipeline with a fast stub; return the captured specs list."""
    captured: list[Any] = []

    def _fake(spec: Any) -> Any:
        captured.append(spec)
        return SimpleNamespace(success=True, image_artifact_id="img-1", error=None)

    monkeypatch.setattr("osfabricum.orchestrator.build.run_pipeline", _fake)
    return captured


# ---------------------------------------------------------------------------
# Plan API
# ---------------------------------------------------------------------------


def test_plan_request_override_changes_packages(db_url: str) -> None:
    base = orchestrator.resolve_plan_request(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url
    )
    assert {p["name"] for p in base["packages"]} == {"pkg-default"}

    overridden = orchestrator.resolve_plan_request(
        distribution="edge-os",
        profile="default",
        board="rpi",
        overrides={"package_set": "set-x"},
        db_url=db_url,
    )
    assert {p["name"] for p in overridden["packages"]} == {"pkg-x"}
    assert base["resolution_hash"] != overridden["resolution_hash"]


def test_plan_validate(db_url: str) -> None:
    ok = orchestrator.validate_plan(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url
    )
    assert ok["valid"] is True
    bad = orchestrator.validate_plan(
        distribution="edge-os", profile="ghost", board="rpi", db_url=db_url
    )
    assert bad["valid"] is False and bad["errors"]


def test_plan_diff(db_url: str) -> None:
    diff = orchestrator.diff_plans(
        distribution="edge-os",
        board="rpi",
        a={"profile": "default"},
        b={"profile": "default", "overrides": {"package_set": "set-x"}},
        db_url=db_url,
    )
    assert diff["packages_added"] == ["pkg-x:1.0"]
    assert diff["packages_removed"] == ["pkg-default:1.0"]
    assert diff["identical"] is False


def test_plan_unknown_override_rejected(db_url: str) -> None:
    with pytest.raises(ValueError, match="unknown package_set"):
        orchestrator.resolve_plan_request(
            distribution="edge-os",
            profile="default",
            board="rpi",
            overrides={"package_set": "nope"},
            db_url=db_url,
        )


# ---------------------------------------------------------------------------
# Build dispatch
# ---------------------------------------------------------------------------


def test_create_build_queues_job_and_records(db_url: str) -> None:
    out = orchestrator.create_build(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url
    )
    assert out["status"] == "queued"
    assert out["job_id"] is not None

    with sync_session(db_url) as s:
        build = s.scalar(select(Build).where(Build.id == out["build_id"]))
        assert build is not None and build.status == "queued"

    assert JobBackend(db_url).queue_depth().get("build.run") == 1

    from osfabricum.pipeline.record import list_build_events

    kinds = {e.event_type for e in list_build_events(out["build_id"], db_url=db_url)}
    assert {"build.request", "build.plan", "build.queued"} <= kinds


def test_create_build_no_enqueue(db_url: str) -> None:
    out = orchestrator.create_build(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url, enqueue=False
    )
    assert out["job_id"] is None
    assert JobBackend(db_url).queue_depth().get("build.run", 0) == 0


def test_claimed_job_runs_pipeline(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_pipeline(monkeypatch)
    out = orchestrator.create_build(
        distribution="edge-os",
        profile="default",
        board="rpi",
        overrides={"package_set": "set-x"},
        db_url=db_url,
    )
    backend = JobBackend(db_url)
    job = backend.claim_next(["build.run"], "worker-test", worker_tags=["arch:aarch64"])
    assert job is not None and job.kind == "build.run"

    result = orchestrator.run_queued_build(job.payload, db_url=db_url, store_root="/tmp/store")
    assert result["success"] is True
    # the executor passed the existing build_id and resolved the override
    assert len(captured) == 1
    assert captured[0].build_id == out["build_id"]
    assert captured[0].overrides and "package_set_id" in captured[0].overrides


def test_rebuild_from_recorded_request(db_url: str) -> None:
    first = orchestrator.create_build(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url, enqueue=False
    )
    again = orchestrator.rebuild(first["build_id"], db_url=db_url, enqueue=False)
    assert again["build_id"] != first["build_id"]
    assert again["resolution_hash"] == first["resolution_hash"]


def test_clone_build_as_profile(db_url: str) -> None:
    out = orchestrator.create_build(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url, enqueue=False
    )
    prof = orchestrator.clone_build_as_profile(out["build_id"], "from-build", db_url=db_url)
    assert prof["name"] == "from-build"
    assert prof["package_set"] == "set-default"


def test_prefetch_report(db_url: str) -> None:
    report = orchestrator.prefetch_report(
        distribution="edge-os", profile="default", board="rpi", db_url=db_url
    )
    assert "resolution_hash" in report
    assert any("pkg-default" in j for j in report["fetch_jobs"])


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


def test_api_plan_validate_diff_prefetch(client: TestClient) -> None:
    r = client.post(
        "/v1/plan",
        json={
            "distribution": "edge-os",
            "profile": "default",
            "board": "rpi",
            "overrides": {"package_set": "set-x"},
        },
    )
    assert r.status_code == 200, r.text
    assert {p["name"] for p in r.json()["packages"]} == {"pkg-x"}

    assert (
        client.post(
            "/v1/plan/validate",
            json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
        ).json()["valid"]
        is True
    )

    diff = client.post(
        "/v1/plan/diff",
        json={
            "distribution": "edge-os",
            "board": "rpi",
            "a": {"profile": "default"},
            "b": {"profile": "default", "overrides": {"package_set": "set-x"}},
        },
    ).json()
    assert diff["packages_added"] == ["pkg-x:1.0"]

    pf = client.post(
        "/v1/prefetch",
        json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
    )
    assert pf.status_code == 200 and "fetch_jobs" in pf.json()


def test_api_create_build_and_rebuild(client: TestClient) -> None:
    r = client.post(
        "/v1/builds",
        json={"distribution": "edge-os", "profile": "default", "board": "rpi"},
    )
    assert r.status_code == 201, r.text
    build_id = r.json()["build_id"]
    assert r.json()["status"] == "queued"

    # it shows up in the build list
    assert any(b["id"] == build_id for b in client.get("/v1/builds").json())
    # artifacts endpoint works (empty until the build runs)
    assert client.get(f"/v1/builds/{build_id}/artifacts").json() == []

    rb = client.post(f"/v1/builds/{build_id}/rebuild")
    assert rb.status_code == 201
    assert rb.json()["build_id"] != build_id

    cp = client.post(f"/v1/builds/{build_id}/clone-as-profile", json={"name": "api-from-build"})
    assert cp.status_code == 201
    assert cp.json()["name"] == "api-from-build"


def test_api_plan_invalid_profile_404(client: TestClient) -> None:
    r = client.post(
        "/v1/plan",
        json={"distribution": "edge-os", "profile": "ghost", "board": "rpi"},
    )
    assert r.status_code == 404
