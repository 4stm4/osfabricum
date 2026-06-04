"""Tests for M18: Build Pipeline (plan→rootfs→image)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

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
from osfabricum.pipeline.record import (
    create_build,
    create_build_job,
    get_build,
    list_build_events,
    list_build_jobs,
    list_builds,
    log_build_event,
    update_build_status,
)

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
    """Minimal DB records for resolve_plan to succeed."""
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


# ---------------------------------------------------------------------------
# pipeline/record.py
# ---------------------------------------------------------------------------


def test_create_build_returns_id(db_url: str, base_data: dict) -> None:
    bid = create_build(
        distribution_id=base_data["dist_id"],
        profile_id=base_data["profile_id"],
        board_id=base_data["board_id"],
        resolution_hash="sha256:" + "a" * 64,
        db_url=db_url,
    )
    assert bid is not None
    assert len(bid) == 36  # UUID


def test_create_build_status_running(db_url: str, base_data: dict) -> None:
    bid = create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "b" * 64,
        db_url=db_url,
    )
    build = get_build(bid, db_url=db_url)
    assert build is not None
    assert build.status == "running"


def test_update_build_status(db_url: str, base_data: dict) -> None:
    bid = create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "c" * 64,
        db_url=db_url,
    )
    update_build_status(bid, "success", db_url=db_url)
    build = get_build(bid, db_url=db_url)
    assert build.status == "success"


def test_list_builds(db_url: str, base_data: dict) -> None:
    for i in range(3):
        create_build(
            base_data["dist_id"],
            base_data["profile_id"],
            base_data["board_id"],
            f"sha256:{'d' * 63}{i}",
            db_url=db_url,
        )
    builds = list_builds(db_url=db_url)
    assert len(builds) == 3


def test_create_build_job(db_url: str, base_data: dict) -> None:
    bid = create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "e" * 64,
        db_url=db_url,
    )
    jid = create_build_job(bid, "rootfs.base", db_url=db_url)
    jobs = list_build_jobs(bid, db_url=db_url)
    assert len(jobs) == 1
    assert jobs[0].step_kind == "rootfs.base"
    assert jobs[0].id == jid


def test_log_build_event(db_url: str, base_data: dict) -> None:
    bid = create_build(
        base_data["dist_id"],
        base_data["profile_id"],
        base_data["board_id"],
        "sha256:" + "f" * 64,
        db_url=db_url,
    )
    log_build_event(bid, "build.start", {"phase": "init"}, db_url=db_url)
    events = list_build_events(bid, db_url=db_url)
    assert len(events) == 1
    assert events[0].event_type == "build.start"


# ---------------------------------------------------------------------------
# run_pipeline — integration
# ---------------------------------------------------------------------------


def _make_spec(base_data: dict, store_root: Path, db_url: str, **kwargs) -> PipelineSpec:
    return PipelineSpec(
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        store_root=store_root,
        db_url=db_url,
        **kwargs,
    )


def test_run_pipeline_succeeds(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    assert result.success is True, result.error
    assert result.rootfs_artifact_id is not None
    assert result.image_artifact_id is not None


def test_run_pipeline_creates_build_record(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    assert result.build_id is not None
    build = get_build(result.build_id, db_url=db_url)
    assert build is not None
    assert build.status == "success"
    assert build.resolution_hash is not None


def test_run_pipeline_creates_build_jobs(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    jobs = list_build_jobs(result.build_id, db_url=db_url)
    step_kinds = {j.step_kind for j in jobs}
    assert "rootfs.base" in step_kinds
    assert "rootfs.compose" in step_kinds
    assert "image.compose" in step_kinds


def test_run_pipeline_all_jobs_success(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    jobs = list_build_jobs(result.build_id, db_url=db_url)
    for j in jobs:
        assert j.status == "success", f"job {j.step_kind} has status {j.status}"


def test_run_pipeline_creates_events(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    events = list_build_events(result.build_id, db_url=db_url)
    event_types = {e.event_type for e in events}
    assert "build.start" in event_types
    assert "build.success" in event_types
    assert "step.start" in event_types
    assert "step.done" in event_types


def test_run_pipeline_completed_steps(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    assert "rootfs.base" in result.steps_completed
    assert "rootfs.compose" in result.steps_completed
    assert "image.compose" in result.steps_completed


def test_run_pipeline_skip_image(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url, skip_image=True)
    result = run_pipeline(spec)
    assert result.success is True
    assert result.rootfs_artifact_id is not None
    assert result.image_artifact_id is None
    assert "image.compose" not in result.steps_completed


def test_run_pipeline_invalid_distribution(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = PipelineSpec(
        distribution="no-such-distro",
        profile="default",
        board="rpi-zero-2w",
        store_root=store_root,
        db_url=db_url,
    )
    result = run_pipeline(spec)
    assert result.success is False
    assert result.error is not None
    assert "plan resolution failed" in result.error


def test_run_pipeline_has_logs(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    assert len(result.logs) > 0
    assert any("[pipeline]" in line for line in result.logs)


def test_run_pipeline_plan_populated(db_url: str, store_root: Path, base_data: dict) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    assert result.plan is not None
    assert result.plan.distribution == "tinywifi"
    assert result.plan.board == "rpi-zero-2w"
    assert result.plan.arch == "aarch64"


def test_run_pipeline_resolution_hash_in_build(
    db_url: str, store_root: Path, base_data: dict
) -> None:
    spec = _make_spec(base_data, store_root, db_url)
    result = run_pipeline(spec)
    build = get_build(result.build_id, db_url=db_url)
    assert build.resolution_hash == result.plan.resolution_hash


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_build_succeeds(db_url: str, store_root: Path, base_data: dict) -> None:
    result = runner.invoke(
        app,
        [
            "build",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "build_id" in result.output or "image" in result.output


def test_cli_build_skip_image(db_url: str, store_root: Path, base_data: dict) -> None:
    result = runner.invoke(
        app,
        [
            "build",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
            "--skip-image",
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_builds_list(db_url: str, store_root: Path, base_data: dict) -> None:
    # Run a build first
    runner.invoke(
        app,
        [
            "build",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
            "--skip-image",
        ],
    )
    result = runner.invoke(app, ["builds", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "tinywifi" in result.output


def test_cli_builds_show(db_url: str, store_root: Path, base_data: dict) -> None:
    # Run a build to get a build_id
    build_result = run_pipeline(
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
        ["builds", "show", build_result.build_id, "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "success" in result.output or "tinywifi" in result.output


def test_cli_builds_logs(db_url: str, store_root: Path, base_data: dict) -> None:
    build_result = run_pipeline(
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
        ["builds", "logs", build_result.build_id, "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "build.start" in result.output
