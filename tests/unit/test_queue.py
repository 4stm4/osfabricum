"""Tests for the M4/M5 job queue (JobBackend, WorkerLoop, CLI, API)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from apps.api.app import create_app
from apps.cli.main import app
from osfabricum.config import Settings
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base, Job
from osfabricum.db.session import sync_session
from osfabricum.queue.backend import JobBackend
from osfabricum.queue.worker import WorkerLoop

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
def backend(db_url: str) -> JobBackend:
    return JobBackend(db_url)


# ---------------------------------------------------------------------------
# JobBackend — basic lifecycle
# ---------------------------------------------------------------------------


def test_enqueue_creates_queued_job(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch", {"uri": "https://example.com/src.tar.gz"})
    assert job_id


def test_claim_returns_none_when_empty(backend: JobBackend) -> None:
    assert backend.claim_next(["source.fetch"], "worker-01") is None


def test_claim_returns_job(backend: JobBackend) -> None:
    backend.enqueue("source.fetch")
    job = backend.claim_next(["source.fetch"], "worker-01")
    assert job is not None
    assert job.kind == "source.fetch"
    assert job.status == "claimed"
    assert job.worker_hostname == "worker-01"


def test_claim_only_matching_kind(backend: JobBackend) -> None:
    backend.enqueue("kernel.build")
    job = backend.claim_next(["source.fetch"], "worker-01")
    assert job is None


def test_complete_marks_completed(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch")
    backend.claim_next(["source.fetch"], "worker-01")
    backend.complete(job_id)
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "completed"


def test_fail_requeues_when_retries_remain(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch", max_attempts=3)
    backend.claim_next(["source.fetch"], "worker-01")
    backend.fail(job_id, "network error")
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "queued"
        assert j.attempt == 2
        assert j.error_message == "network error"


def test_fail_marks_failed_when_no_retries(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch", max_attempts=1)
    backend.claim_next(["source.fetch"], "worker-01")
    backend.fail(job_id, "unrecoverable")
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "failed"


def test_fail_manual_policy_never_requeues(backend: JobBackend) -> None:
    job_id = backend.enqueue("kernel.build", max_attempts=5, retry_policy="manual")
    backend.claim_next(["kernel.build"], "worker-01")
    backend.fail(job_id, "needs manual intervention")
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "failed"


# ---------------------------------------------------------------------------
# JobBackend — lease expiry
# ---------------------------------------------------------------------------


def test_expire_leases_requeues_stale(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch", lease_ttl_s=0)
    backend.claim_next(["source.fetch"], "worker-01")
    # lease_ttl_s=0 means immediately expired
    time.sleep(0.01)
    count = backend.expire_leases()
    assert count == 1
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "queued"
        assert j.attempt == 2


def test_expire_leases_fails_when_max_attempts_exhausted(backend: JobBackend) -> None:
    job_id = backend.enqueue("source.fetch", max_attempts=1, lease_ttl_s=0)
    backend.claim_next(["source.fetch"], "worker-01")
    time.sleep(0.01)
    backend.expire_leases()
    with sync_session(backend._db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "failed"


def test_expire_leases_ignores_active(backend: JobBackend) -> None:
    backend.enqueue("source.fetch", lease_ttl_s=3600)
    backend.claim_next(["source.fetch"], "worker-01")
    count = backend.expire_leases()
    assert count == 0


# ---------------------------------------------------------------------------
# JobBackend — observability
# ---------------------------------------------------------------------------


def test_queue_depth_counts_queued(backend: JobBackend) -> None:
    backend.enqueue("source.fetch")
    backend.enqueue("source.fetch")
    backend.enqueue("kernel.build")
    depth = backend.queue_depth()
    assert depth["source.fetch"] == 2
    assert depth["kernel.build"] == 1


def test_status_counts(backend: JobBackend) -> None:
    backend.enqueue("source.fetch")
    backend.enqueue("source.fetch")
    backend.claim_next(["source.fetch"], "w")
    counts = backend.status_counts()
    assert counts.get("queued", 0) == 1
    assert counts.get("claimed", 0) == 1


# ---------------------------------------------------------------------------
# WorkerLoop
# ---------------------------------------------------------------------------


def test_worker_loop_executes_and_completes(db_url: str) -> None:
    backend = JobBackend(db_url)
    job_id = backend.enqueue("test.noop")
    executed: list[str] = []

    def handler(job: Job) -> None:
        executed.append(job.id)

    loop = WorkerLoop(backend, "test-worker", ["test.noop"], poll_interval_s=0.05)
    loop.register("test.noop", handler)

    stop = threading.Event()

    def _run() -> None:
        loop.run(stop)

    t = threading.Thread(target=_run)
    t.start()
    # Wait for the job to be processed
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with sync_session(db_url) as session:
            j = session.get(Job, job_id)
            if j and j.status == "completed":
                break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=2)

    assert job_id in executed
    with sync_session(db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "completed"


def test_worker_loop_fails_job_on_handler_exception(db_url: str) -> None:
    backend = JobBackend(db_url)
    job_id = backend.enqueue("test.boom", max_attempts=1)

    def boom(job: Job) -> None:
        raise RuntimeError("handler error")

    loop = WorkerLoop(backend, "test-worker", ["test.boom"], poll_interval_s=0.05)
    loop.register("test.boom", boom)

    stop = threading.Event()
    t = threading.Thread(target=loop.run, args=(stop,))
    t.start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with sync_session(db_url) as session:
            j = session.get(Job, job_id)
            if j and j.status == "failed":
                break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=2)

    with sync_session(db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "failed"


def test_worker_loop_fails_job_no_handler(db_url: str) -> None:
    backend = JobBackend(db_url)
    job_id = backend.enqueue("unknown.kind", max_attempts=1)
    loop = WorkerLoop(backend, "test-worker", ["unknown.kind"], poll_interval_s=0.05)

    stop = threading.Event()
    t = threading.Thread(target=loop.run, args=(stop,))
    t.start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with sync_session(db_url) as session:
            j = session.get(Job, job_id)
            if j and j.status == "failed":
                break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=2)


# ---------------------------------------------------------------------------
# CLI: workers list
# ---------------------------------------------------------------------------


def test_cli_workers_list_empty(db_url: str) -> None:
    result = runner.invoke(app, ["workers", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Workers" in result.output


# ---------------------------------------------------------------------------
# API: /internal/queue + /metrics with queue depth
# ---------------------------------------------------------------------------


def test_api_internal_queue_empty(db_url: str) -> None:
    settings = Settings()
    settings.database.url = db_url
    api = create_app(settings)
    with TestClient(api) as client:
        resp = client.get("/internal/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert "queue_depth" in data
    assert data["queue_depth"] == {}


def test_api_metrics_includes_queue_depth(db_url: str) -> None:
    backend = JobBackend(db_url)
    backend.enqueue("source.fetch")
    settings = Settings()
    settings.database.url = db_url
    api = create_app(settings)
    with TestClient(api) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert 'osf_job_queue_depth{kind="source.fetch"}' in resp.text


# ---------------------------------------------------------------------------
# M5: capability routing (required_tags / worker_tags)
# ---------------------------------------------------------------------------


def test_claim_no_tags_matches_any_worker(backend: JobBackend) -> None:
    """Job with no required_tags can be claimed by a worker with no tags."""
    backend.enqueue("source.fetch", required_tags=[])
    job = backend.claim_next(["source.fetch"], "plain-worker", worker_tags=[])
    assert job is not None


def test_claim_required_tags_match(backend: JobBackend) -> None:
    backend.enqueue("kernel.build", required_tags=["arch:aarch64", "cap:kernel"])
    job = backend.claim_next(
        ["kernel.build"],
        "rpi-worker",
        worker_tags=["arch:aarch64", "cap:kernel", "cap:qemu"],
    )
    assert job is not None


def test_claim_required_tags_no_match(backend: JobBackend) -> None:
    """Worker without required tags cannot claim the job."""
    backend.enqueue("kernel.build", required_tags=["arch:aarch64"])
    job = backend.claim_next(
        ["kernel.build"],
        "x86-worker",
        worker_tags=["arch:x86_64"],
    )
    assert job is None


def test_claim_cap_qemu_routing(backend: JobBackend) -> None:
    """Worker with cap:qemu=false (no cap:qemu tag) cannot claim image.test."""
    backend.enqueue("image.test", required_tags=["cap:qemu"])

    # Worker without cap:qemu cannot claim it
    no_qemu = backend.claim_next(
        ["image.test"],
        "worker-no-qemu",
        worker_tags=["arch:x86_64"],
    )
    assert no_qemu is None

    # Worker with cap:qemu can claim it
    with_qemu = backend.claim_next(
        ["image.test"],
        "worker-with-qemu",
        worker_tags=["arch:x86_64", "cap:qemu"],
    )
    assert with_qemu is not None


def test_claim_arch_routing(backend: JobBackend) -> None:
    """x86_64 worker never receives kernel.build jobs tagged arch:aarch64."""
    backend.enqueue("kernel.build", required_tags=["arch:aarch64"])

    # x86_64 worker cannot claim it
    x86_job = backend.claim_next(
        ["kernel.build"],
        "worker-x86",
        worker_tags=["arch:x86_64"],
    )
    assert x86_job is None

    # aarch64 worker can claim it
    arm_job = backend.claim_next(
        ["kernel.build"],
        "worker-arm",
        worker_tags=["arch:aarch64", "cap:kernel"],
    )
    assert arm_job is not None


def test_claim_skips_mismatched_picks_matching(backend: JobBackend) -> None:
    """If first queued job requires tags worker lacks, next matching job is claimed."""
    backend.enqueue("package.build", required_tags=["arch:aarch64"])
    backend.enqueue("package.build", required_tags=["arch:x86_64"])

    job = backend.claim_next(
        ["package.build"],
        "x86-worker",
        worker_tags=["arch:x86_64"],
    )
    assert job is not None
    assert job.required_tags_json == ["arch:x86_64"]


def test_worker_loop_tag_routing(db_url: str) -> None:
    """WorkerLoop with arch:aarch64 tag cannot claim job requiring arch:x86_64."""
    backend = JobBackend(db_url)
    job_id = backend.enqueue("package.build", required_tags=["arch:x86_64"], max_attempts=1)

    executed: list[str] = []

    def handler(job: Job) -> None:
        executed.append(job.id)

    loop = WorkerLoop(
        backend,
        "arm-worker",
        ["package.build"],
        worker_tags=["arch:aarch64"],
        poll_interval_s=0.05,
    )
    loop.register("package.build", handler)

    stop = threading.Event()
    t = threading.Thread(target=loop.run, args=(stop,))
    t.start()
    time.sleep(0.3)
    stop.set()
    t.join(timeout=2)

    # Job was not executed by the aarch64 worker
    assert job_id not in executed
    with sync_session(db_url) as session:
        j = session.get(Job, job_id)
        assert j is not None
        assert j.status == "queued"
