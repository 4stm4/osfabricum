"""Tests for M19: Build History / Logs."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from apps.api.app import create_app
from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Base,
    Board,
    Distribution,
    Profile,
)
from osfabricum.db.session import sync_session
from osfabricum.pipeline.coordinator import PipelineSpec, run_pipeline
from osfabricum.pipeline.log import (
    build_summary,
    count_build_logs,
    get_build_logs,
    search_builds,
    write_build_log,
    write_build_logs,
)
from osfabricum.pipeline.record import create_build, get_build

runner = CliRunner()

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
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture()
def base_data(db_url: str) -> dict:
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
        dist = Distribution(name="tinywifi", default_channel="dev")
        session.add(dist)
        session.flush()
        prof = Profile(distribution_id=dist.id, name="default")
        session.add(prof)
        session.commit()
        return {
            "arch_id": arch.id,
            "board_id": board.id,
            "dist_id": dist.id,
            "profile_id": prof.id,
        }


@pytest.fixture()
def build_id(db_url: str, base_data: dict) -> str:
    return create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "a" * 64,
        db_url=db_url,
    )


@pytest.fixture()
def api_client(db_url: str) -> TestClient:
    from osfabricum.settings import Settings

    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))


# ---------------------------------------------------------------------------
# write_build_log / write_build_logs
# ---------------------------------------------------------------------------


def test_write_build_log_single(db_url: str, build_id: str) -> None:
    write_build_log(build_id, "line 1", db_url=db_url)
    logs = get_build_logs(build_id, db_url=db_url)
    assert len(logs) == 1
    assert logs[0].message == "line 1"


def test_write_build_logs_bulk(db_url: str, build_id: str) -> None:
    n = write_build_logs(build_id, ["a", "b", "c"], db_url=db_url)
    assert n == 3
    logs = get_build_logs(build_id, db_url=db_url)
    assert len(logs) == 3


def test_write_build_log_with_job_id(db_url: str, build_id: str) -> None:
    from osfabricum.pipeline.record import create_build_job

    job_id = create_build_job(build_id, "rootfs.base", db_url=db_url)
    write_build_log(build_id, "step log", job_id=job_id, db_url=db_url)
    logs = get_build_logs(build_id, job_id=job_id, db_url=db_url)
    assert len(logs) == 1
    assert logs[0].job_id == job_id


def test_write_build_log_stream_filter(db_url: str, build_id: str) -> None:
    write_build_log(build_id, "stdout line", stream="stdout", db_url=db_url)
    write_build_log(build_id, "stderr line", stream="stderr", db_url=db_url)
    stdout = get_build_logs(build_id, stream="stdout", db_url=db_url)
    stderr = get_build_logs(build_id, stream="stderr", db_url=db_url)
    assert len(stdout) == 1
    assert len(stderr) == 1
    assert stdout[0].message == "stdout line"
    assert stderr[0].message == "stderr line"


def test_write_build_logs_empty(db_url: str, build_id: str) -> None:
    n = write_build_logs(build_id, [], db_url=db_url)
    assert n == 0


def test_count_build_logs(db_url: str, build_id: str) -> None:
    write_build_logs(build_id, ["x"] * 7, db_url=db_url)
    assert count_build_logs(build_id, db_url=db_url) == 7


def test_get_build_logs_pagination(db_url: str, build_id: str) -> None:
    write_build_logs(build_id, [f"line {i}" for i in range(20)], db_url=db_url)
    page1 = get_build_logs(build_id, limit=5, offset=0, db_url=db_url)
    page2 = get_build_logs(build_id, limit=5, offset=5, db_url=db_url)
    assert len(page1) == 5
    assert len(page2) == 5
    assert page1[0].line_no == 0
    assert page2[0].line_no == 5


# ---------------------------------------------------------------------------
# search_builds
# ---------------------------------------------------------------------------


def test_search_builds_all(db_url: str, base_data: dict) -> None:
    for i in range(3):
        create_build(
            base_data["dist_id"],
            base_data["profile_id"],
            base_data["board_id"],
            f"sha256:{'b' * 63}{i}",
            db_url=db_url,
        )
    builds = search_builds(db_url=db_url)
    assert len(builds) == 3


def test_search_builds_by_status(db_url: str, base_data: dict) -> None:
    from osfabricum.pipeline.record import update_build_status

    bid = create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "c" * 64,
        db_url=db_url,
    )
    update_build_status(bid, "success", db_url=db_url)
    create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "d" * 64,
        db_url=db_url,
    )
    successes = search_builds(status="success", db_url=db_url)
    assert all(b.status == "success" for b in successes)
    assert len(successes) == 1


def test_search_builds_by_distribution(db_url: str, base_data: dict) -> None:
    create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "e" * 64,
        db_url=db_url,
    )
    found = search_builds(distribution_name="tinywifi", db_url=db_url)
    assert len(found) == 1

    not_found = search_builds(distribution_name="no-such-distro", db_url=db_url)
    assert not_found == []


def test_search_builds_by_board_id(db_url: str, base_data: dict) -> None:
    create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "f" * 64,
        db_url=db_url,
    )
    found = search_builds(board_id=base_data["board_id"], db_url=db_url)
    assert len(found) == 1


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------


def test_build_summary_structure(db_url: str, build_id: str) -> None:
    summary = build_summary(build_id, db_url=db_url)
    assert summary is not None
    assert summary["id"] == build_id
    assert "status" in summary
    assert "jobs" in summary
    assert "event_count" in summary
    assert "log_line_count" in summary


def test_build_summary_not_found(db_url: str) -> None:
    result = build_summary("00000000-0000-0000-0000-000000000000", db_url=db_url)
    assert result is None


def test_build_summary_log_count(db_url: str, build_id: str) -> None:
    write_build_logs(build_id, ["x", "y", "z"], db_url=db_url)
    summary = build_summary(build_id, db_url=db_url)
    assert summary["log_line_count"] == 3


# ---------------------------------------------------------------------------
# Pipeline integration: BuildLog is populated after run_pipeline
# ---------------------------------------------------------------------------


def test_pipeline_writes_build_logs(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = PipelineSpec(
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        store_root=store_root,
        db_url=db_url,
        skip_image=True,
    )
    result = run_pipeline(spec)
    assert result.success
    # Each step with a .logs attribute should have persisted its lines
    logs = get_build_logs(result.build_id, db_url=db_url)
    # rootfs.base and rootfs.compose both produce logs
    assert len(logs) > 0


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


def test_api_list_builds_empty(api_client: TestClient) -> None:
    resp = api_client.get("/v1/builds")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_list_builds_returns_data(api_client: TestClient, db_url: str, base_data: dict) -> None:
    create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "g" * 64,
        db_url=db_url,
    )
    resp = api_client.get("/v1/builds")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "running"


def test_api_get_build_summary(api_client: TestClient, db_url: str, build_id: str) -> None:
    resp = api_client.get(f"/v1/builds/{build_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == build_id
    assert "jobs" in data
    assert "log_line_count" in data


def test_api_get_build_not_found(api_client: TestClient) -> None:
    resp = api_client.get("/v1/builds/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_api_get_build_events(api_client: TestClient, db_url: str, build_id: str) -> None:
    from osfabricum.pipeline.record import log_build_event

    log_build_event(build_id, "test.event", {"k": "v"}, db_url=db_url)
    resp = api_client.get(f"/v1/builds/{build_id}/events")
    assert resp.status_code == 200
    events = resp.json()
    assert any(e["event_type"] == "test.event" for e in events)


def test_api_get_build_logs(api_client: TestClient, db_url: str, build_id: str) -> None:
    write_build_logs(build_id, ["log line 1", "log line 2"], db_url=db_url)
    resp = api_client.get(f"/v1/builds/{build_id}/logs")
    assert resp.status_code == 200
    lines = resp.json()
    assert len(lines) == 2
    assert lines[0]["message"] == "log line 1"


def test_api_get_build_logs_pagination(api_client: TestClient, db_url: str, build_id: str) -> None:
    write_build_logs(build_id, [f"line {i}" for i in range(10)], db_url=db_url)
    resp = api_client.get(f"/v1/builds/{build_id}/logs?limit=3&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_api_cancel_build(api_client: TestClient, db_url: str, build_id: str) -> None:
    resp = api_client.post(f"/v1/builds/{build_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    build = get_build(build_id, db_url=db_url)
    assert build.status == "cancelled"


def test_api_cancel_already_finished(api_client: TestClient, db_url: str, build_id: str) -> None:
    from osfabricum.pipeline.record import update_build_status

    update_build_status(build_id, "success", db_url=db_url)
    resp = api_client.post(f"/v1/builds/{build_id}/cancel")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# CLI: builds list with filters, builds show --logs
# ---------------------------------------------------------------------------


def test_cli_builds_list_filter_status(db_url: str, store_root: Path, base_data: dict) -> None:
    run_pipeline(
        PipelineSpec(
            distribution="tinywifi",
            profile="default",
            board="rpi-zero-2w",
            store_root=store_root,
            db_url=db_url,
            skip_image=True,
        )
    )
    result = runner.invoke(app, ["builds", "list", "--status", "success", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "success" in result.output


def test_cli_builds_list_filter_distribution(
    db_url: str, store_root: Path, base_data: dict
) -> None:
    run_pipeline(
        PipelineSpec(
            distribution="tinywifi",
            profile="default",
            board="rpi-zero-2w",
            store_root=store_root,
            db_url=db_url,
            skip_image=True,
        )
    )
    result = runner.invoke(
        app, ["builds", "list", "--distribution", "tinywifi", "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "tinywifi" in result.output


def test_cli_builds_show_with_logs(db_url: str, store_root: Path, base_data: dict) -> None:
    pr = run_pipeline(
        PipelineSpec(
            distribution="tinywifi",
            profile="default",
            board="rpi-zero-2w",
            store_root=store_root,
            db_url=db_url,
            skip_image=True,
        )
    )
    result = runner.invoke(
        app,
        ["builds", "show", pr.build_id, "--logs", "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    # Log lines should be printed
    assert "log" in result.output.lower() or "[" in result.output
