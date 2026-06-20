"""REST API routes for workers.

GET    /v1/workers                  — list workers + online count + limits
GET    /v1/workers/install-command  — shell command to run a remote worker
POST   /v1/workers/spawn            — spawn a new local worker subprocess
DELETE /v1/workers/{worker_id}      — stop a local worker via SIGTERM
GET    /v1/workers/{hostname}       — single worker detail
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from osfabricum.db.models import Worker
from osfabricum.db.session import sync_session

router = APIRouter(prefix="/v1/workers", tags=["workers"])

_ONLINE_THRESHOLD_S = 30


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url
    except AttributeError:
        return None


def _max_workers(req: Request) -> int:
    try:
        return req.app.state.settings.worker.max_local_workers
    except AttributeError:
        return 4


def _sync_db_url(url: str) -> str:
    """Strip async driver suffix (+aiosqlite / +asyncpg) so the worker can use it."""
    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def _is_online(w: Worker) -> bool:
    if w.last_seen_at is None:
        return False
    threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=_ONLINE_THRESHOLD_S)
    return w.last_seen_at >= threshold


class WorkerItem(BaseModel):
    id: str
    hostname: str
    enabled: bool
    kinds: list[str]
    tags: list[str]
    last_seen_at: str | None
    online: bool
    pid: int | None


class WorkersListResponse(BaseModel):
    workers: list[WorkerItem]
    online_count: int
    max_local_workers: int


class SpawnRequest(BaseModel):
    kinds: str = "build.run,package.build,rootfs.compose,image.compose"
    tags: str | None = None


def _to_item(w: Worker) -> WorkerItem:
    return WorkerItem(
        id=w.id,
        hostname=w.hostname,
        enabled=w.enabled,
        kinds=list(w.kinds_json or []),
        tags=list(w.tags_json or []),
        last_seen_at=w.last_seen_at.isoformat() if w.last_seen_at else None,
        online=_is_online(w),
        pid=getattr(w, "pid", None),
    )


@router.get("", response_model=WorkersListResponse)
def list_workers(request: Request) -> WorkersListResponse:
    """List all registered workers with online/offline status."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        workers = session.scalars(select(Worker).order_by(Worker.hostname)).all()
        items = [_to_item(w) for w in workers]
    return WorkersListResponse(
        workers=items,
        online_count=sum(1 for w in items if w.online),
        max_local_workers=_max_workers(request),
    )


@router.get("/install-command")
def install_command(request: Request) -> dict[str, Any]:
    """Return a shell command to run a worker on a remote host."""
    try:
        raw_url = request.app.state.settings.database.url
    except AttributeError:
        raw_url = ""

    if "sqlite" in raw_url.lower():
        return {
            "command": None,
            "warning": (
                "Remote workers require a shared database. "
                "SQLite is a local file and cannot be accessed over the network. "
                "Switch to PostgreSQL and set database.url accordingly."
            ),
        }

    # Replace docker-internal hostname with the real host IP so the command
    # works on a machine outside the Docker network.
    api_host = request.url.hostname or "HOST"
    db_url = _sync_db_url(re.sub(r"@([^@:/]+)([:/])", f"@{api_host}\\2", raw_url))

    cmd = (
        "docker run -d --name osfabricum-worker \\\n"
        f"  -e OSFABRICUM_DB_URL='{db_url}' \\\n"
        "  osfabricum:latest \\\n"
        "  osfabricum-worker \\\n"
        "    --worker-id \"remote-$(hostname)\" \\\n"
        f"    --db-url '{db_url}' \\\n"
        "    --kinds 'build.run,package.build,rootfs.compose,image.compose' \\\n"
        "    --tags \"arch:$(uname -m)\""
    )
    return {"command": cmd, "warning": None}


@router.post("/spawn", response_model=WorkerItem)
def spawn_worker(request: Request, body: SpawnRequest = SpawnRequest()) -> WorkerItem:
    """Spawn a new local worker subprocess."""
    db_url = _db(request)
    max_w = _max_workers(request)

    with sync_session(db_url) as session:
        all_workers = session.scalars(select(Worker).order_by(Worker.hostname)).all()
        online_count = sum(1 for w in all_workers if _is_online(w))
        if online_count >= max_w:
            raise HTTPException(
                status_code=409,
                detail=f"Already at maximum local workers ({max_w}). Stop one before adding another.",
            )
        existing_ids = {w.hostname for w in all_workers}

    # pick next worker-NN id
    n = 1
    while f"worker-{n:02d}" in existing_ids:
        n += 1
    worker_id = f"worker-{n:02d}"

    # resolve db_url for the child process (must be sync)
    try:
        raw_db = request.app.state.settings.database.url
    except AttributeError:
        raw_db = ""
    sync_url = _sync_db_url(raw_db) or os.environ.get("OSFABRICUM_DB_URL", "")
    if not sync_url:
        raise HTTPException(status_code=503, detail="Cannot determine DB URL for new worker")

    tags = body.tags or f"arch:{platform.machine()}"
    exe = shutil.which("osfabricum-worker") or "osfabricum-worker"

    proc = subprocess.Popen(
        [exe, "--worker-id", worker_id, "--db-url", sync_url,
         "--kinds", body.kinds, "--tags", tags],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # worker registers itself within a few seconds; return a placeholder
    return WorkerItem(
        id="",
        hostname=worker_id,
        enabled=True,
        kinds=body.kinds.split(","),
        tags=tags.split(","),
        last_seen_at=None,
        online=False,
        pid=proc.pid,
    )


@router.delete("/{worker_id}")
def stop_worker(worker_id: str, request: Request) -> dict[str, Any]:
    """Send SIGTERM to a local worker identified by its worker_id (hostname)."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        w = session.scalar(select(Worker).where(Worker.hostname == worker_id))
        if w is None:
            raise HTTPException(status_code=404, detail=f"Worker {worker_id!r} not found")
        pid = getattr(w, "pid", None)

    if pid is None:
        raise HTTPException(
            status_code=422,
            detail="Worker has no PID recorded — cannot stop remotely registered workers via the API",
        )

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # already exited

    return {"worker_id": worker_id, "pid": pid, "status": "stopping"}


@router.get("/{hostname}", response_model=WorkerItem)
def get_worker(hostname: str, request: Request) -> WorkerItem:
    """Return details for a single worker by hostname."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        w = session.scalar(select(Worker).where(Worker.hostname == hostname))
        if w is None:
            raise HTTPException(status_code=404, detail=f"Worker {hostname!r} not found")
        return _to_item(w)
