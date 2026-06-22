"""REST API routes for builds (M19).

Implements the ``/v1/builds`` surface from ROADMAP section 6:

    GET  /v1/builds              — list builds (with filters)
    GET  /v1/builds/{id}         — build summary
    GET  /v1/builds/{id}/events  — event list
    GET  /v1/builds/{id}/logs    — paged log lines
    POST /v1/builds/{id}/cancel  — cancel a running build (stub)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from osfabricum.pipeline.log import build_summary, get_build_logs, search_builds
from osfabricum.pipeline.record import get_build, list_build_events
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1/builds", tags=["builds"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class JobSummary(BaseModel):
    id: str
    step_kind: str
    status: str


class BuildSummaryResponse(BaseModel):
    id: str
    distribution_id: str
    profile_id: str
    board_id: str
    resolution_hash: str | None
    status: str
    created_at: str | None
    updated_at: str | None
    jobs: list[JobSummary]
    event_count: int
    log_line_count: int


class BuildListItem(BaseModel):
    id: str
    distribution_id: str
    profile_id: str
    board_id: str
    distribution: str | None = None
    profile: str | None = None
    board: str | None = None
    arch: str | None = None
    resolution_hash: str | None = None
    status: str
    created_at: str | None


class EventItem(BaseModel):
    id: str
    event_type: str
    ts: str | None
    payload: dict[str, Any]


class LogLineItem(BaseModel):
    id: str
    job_id: str | None
    ts: str | None
    stream: str
    line_no: int | None
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db_url(request: Request) -> str | None:  # type: ignore[no-untyped-def]
    """Extract db_url from app state (set by create_app)."""
    try:
        settings = request.app.state.settings
        return settings.database.url
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[BuildListItem])
def list_builds_api(
    request: Request,
    distribution: Annotated[str | None, Query(description="Filter by distribution name")] = None,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    board_id: Annotated[str | None, Query(description="Filter by board UUID")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[BuildListItem]:
    """List builds with optional filters (resolved to readable names)."""
    from sqlalchemy import select  # noqa: PLC0415

    from osfabricum.db.models import Architecture, Board, Distribution, Profile  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    db_url = _get_db_url(request)
    builds = search_builds(
        distribution_name=distribution,
        status=status,
        board_id=board_id,
        limit=limit,
        db_url=db_url,
    )
    with sync_session(db_url) as s:
        dist_names = {d.id: d.name for d in s.scalars(select(Distribution)).all()}
        prof_names = {p.id: p.name for p in s.scalars(select(Profile)).all()}
        boards = {b.id: b for b in s.scalars(select(Board)).all()}
        arch_names = {a.id: a.name for a in s.scalars(select(Architecture)).all()}

    items: list[BuildListItem] = []
    for b in builds:
        board = boards.get(b.board_id)
        items.append(
            BuildListItem(
                id=b.id,
                distribution_id=b.distribution_id,
                profile_id=b.profile_id,
                board_id=b.board_id,
                distribution=dist_names.get(b.distribution_id),
                profile=prof_names.get(b.profile_id),
                board=board.name if board is not None else None,
                arch=arch_names.get(board.arch_id) if board is not None else None,
                resolution_hash=b.resolution_hash,
                status=b.status,
                created_at=b.created_at.isoformat() if b.created_at else None,
            )
        )
    return items


@router.get("/{build_id}", response_model=BuildSummaryResponse)
def get_build_api(build_id: str, request: Request) -> BuildSummaryResponse:
    """Return a full build summary including jobs and log count."""
    db_url = _get_db_url(request)
    summary = build_summary(build_id, db_url=db_url)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
    jobs = [JobSummary(**j) for j in summary.pop("jobs", [])]
    return BuildSummaryResponse(**summary, jobs=jobs)


@router.get("/{build_id}/events", response_model=list[EventItem])
def get_build_events_api(build_id: str, request: Request) -> list[EventItem]:
    """Return the event stream for a build."""
    db_url = _get_db_url(request)
    build = get_build(build_id, db_url=db_url)
    if build is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
    events = list_build_events(build_id, db_url=db_url)
    return [
        EventItem(
            id=ev.id,
            event_type=ev.event_type,
            ts=ev.ts.isoformat() if ev.ts else None,
            payload=ev.payload_json or {},
        )
        for ev in events
    ]


@router.get("/{build_id}/events/stream")
def stream_build_events_api(build_id: str, request: Request) -> StreamingResponse:
    """Stream build events as Server-Sent Events (SSE).

    Emits each event as ``data: {json}\\n\\n``.  Polls the database every
    second and emits new events until the build reaches a terminal state
    (``success`` / ``failed`` / ``cancelled``) or the client disconnects.
    """
    import asyncio  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    db_url = _get_db_url(request)
    build = get_build(build_id, db_url=db_url)
    if build is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")

    _terminal = {"success", "failed", "cancelled"}

    async def _event_gen():
        seen: set[str] = set()
        # Bound the stream so a hung build cannot keep the connection open
        # forever; ~5 minutes at 1 s polling.
        for _ in range(300):
            if await request.is_disconnected():
                break
            events = list_build_events(build_id, db_url=db_url)
            for ev in events:
                if ev.id in seen:
                    continue
                seen.add(ev.id)
                payload = {
                    "id": ev.id,
                    "event_type": ev.event_type,
                    "ts": ev.ts.isoformat() if ev.ts else None,
                    "payload": ev.payload_json or {},
                }
                yield f"data: {_json.dumps(payload)}\n\n"

            current = get_build(build_id, db_url=db_url)
            if current is not None and current.status in _terminal:
                yield f"event: end\ndata: {_json.dumps({'status': current.status})}\n\n"
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(_event_gen(), media_type="text/event-stream")


@router.get("/{build_id}/logs", response_model=list[LogLineItem])
def get_build_logs_api(
    build_id: str,
    request: Request,
    job_id: Annotated[str | None, Query()] = None,
    stream: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LogLineItem]:
    """Return paginated log lines for a build."""
    db_url = _get_db_url(request)
    build = get_build(build_id, db_url=db_url)
    if build is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
    lines = get_build_logs(
        build_id,
        job_id=job_id,
        stream=stream,
        limit=limit,
        offset=offset,
        db_url=db_url,
    )
    return [
        LogLineItem(
            id=ln.id,
            job_id=ln.job_id,
            ts=ln.ts.isoformat() if ln.ts else None,
            stream=ln.stream,
            line_no=ln.line_no,
            message=ln.message,
        )
        for ln in lines
    ]


@router.post("/{build_id}/cancel")
def cancel_build_api(build_id: str, request: Request, _auth: WriteAuthDep = None) -> dict[str, str]:
    """Cancel a running build (stub — sets status to 'cancelled')."""
    from osfabricum.pipeline.record import update_build_status  # noqa: PLC0415

    db_url = _get_db_url(request)
    build = get_build(build_id, db_url=db_url)
    if build is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
    if build.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Build is already in terminal state: {build.status!r}",
        )
    update_build_status(build_id, "cancelled", db_url=db_url)
    return {"id": build_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Write API (M29) — create / rebuild / clone-as-profile / artifacts
# ---------------------------------------------------------------------------


class CreateBuildRequest(BaseModel):
    distribution: str
    profile: str
    board: str
    store_root: str | None = None
    overrides: dict[str, Any] | None = None


class CloneAsProfileRequest(BaseModel):
    name: str


def _build_guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.post("", status_code=201)
def create_build_api(
    body: CreateBuildRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Create a build: resolve plan, record it, enqueue a build.run job."""
    from osfabricum import orchestrator  # noqa: PLC0415

    try:
        return orchestrator.create_build(
            distribution=body.distribution,
            profile=body.profile,
            board=body.board,
            store_root=body.store_root,
            overrides=body.overrides,
            db_url=_get_db_url(request),
        )
    except ValueError as exc:
        raise _build_guard(exc) from exc


@router.post("/{build_id}/rebuild", status_code=201)
def rebuild_api(build_id: str, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    from osfabricum import orchestrator  # noqa: PLC0415

    try:
        return orchestrator.rebuild(build_id, db_url=_get_db_url(request))
    except ValueError as exc:
        raise _build_guard(exc) from exc


@router.post("/{build_id}/clone-as-profile", status_code=201)
def clone_as_profile_api(
    build_id: str, body: CloneAsProfileRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    from osfabricum import orchestrator  # noqa: PLC0415

    try:
        return orchestrator.clone_build_as_profile(build_id, body.name, db_url=_get_db_url(request))
    except ValueError as exc:
        raise _build_guard(exc) from exc


@router.get("/{build_id}/artifacts")
def build_artifacts_api(build_id: str, request: Request) -> list[dict[str, Any]]:
    from sqlalchemy import select  # noqa: PLC0415

    from osfabricum.db.models import Artifact  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    db_url = _get_db_url(request)
    if get_build(build_id, db_url=db_url) is None:
        raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
    with sync_session(db_url) as s:
        rows = s.scalars(select(Artifact).where(Artifact.producer_build_id == build_id)).all()
        return [
            {
                "id": a.id,
                "kind": a.kind,
                "name": a.name,
                "arch": a.arch,
                "blob_sha256": a.blob_sha256,
                "size_bytes": a.size_bytes,
            }
            for a in rows
        ]


# ---------------------------------------------------------------------------
# Delete endpoints
# ---------------------------------------------------------------------------

def _delete_builds(build_ids: list[str], db_url: str | None) -> int:
    """Delete builds and all their associated rows. Returns deleted count."""
    from sqlalchemy import delete as _del  # noqa: PLC0415
    from osfabricum.db.models import Build, BuildEvent, BuildJob, BuildLog  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    if not build_ids:
        return 0
    with sync_session(db_url) as s:
        # Order matters: child rows first due to FK constraints
        s.execute(_del(BuildLog).where(BuildLog.build_id.in_(build_ids)))
        s.execute(_del(BuildEvent).where(BuildEvent.build_id.in_(build_ids)))
        s.execute(_del(BuildJob).where(BuildJob.build_id.in_(build_ids)))
        result = s.execute(_del(Build).where(Build.id.in_(build_ids)))
        s.commit()
        return result.rowcount


@router.delete("/{build_id}", status_code=200)
def delete_build_api(
    build_id: str, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Delete a single build and all its jobs/events/logs."""
    from osfabricum.db.models import Build  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    db_url = _get_db_url(request)
    with sync_session(db_url) as s:
        build = s.get(Build, build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"Build {build_id!r} not found")
        if build.status in ("running", "queued"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete build in state {build.status!r} — cancel it first",
            )

    deleted = _delete_builds([build_id], db_url)
    return {"deleted": deleted, "ids": [build_id]}


@router.delete("", status_code=200)
def delete_builds_bulk_api(
    request: Request,
    _auth: WriteAuthDep = None,
    status: str | None = Query(default=None, description="Only delete builds with this status (e.g. 'failed', 'success')"),
    distribution: str | None = Query(default=None, description="Only delete builds for this distribution name"),
    keep_latest: int = Query(default=0, ge=0, description="Keep this many most-recent builds (0 = delete all matching)"),
) -> dict[str, Any]:
    """Bulk-delete builds matching the given filters.

    At least one of ``status``, ``distribution``, or ``keep_latest`` must be
    provided to prevent accidental deletion of everything.
    Running/queued builds are always skipped.
    """
    from sqlalchemy import select as _sel  # noqa: PLC0415
    from osfabricum.db.models import Build, Distribution  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    if status is None and distribution is None and keep_latest == 0:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one filter: status, distribution, or keep_latest",
        )

    db_url = _get_db_url(request)
    with sync_session(db_url) as s:
        q = _sel(Build).where(Build.status.notin_(["running", "queued"]))

        if status is not None:
            q = q.where(Build.status == status)

        if distribution is not None:
            dist_row = s.scalar(_sel(Distribution).where(Distribution.name == distribution))
            if dist_row is None:
                raise HTTPException(status_code=404, detail=f"Distribution {distribution!r} not found")
            q = q.where(Build.distribution_id == dist_row.id)

        q = q.order_by(Build.created_at.desc())
        builds = s.scalars(q).all()

        if keep_latest > 0:
            builds = builds[keep_latest:]  # skip the N newest, delete the rest

        ids = [b.id for b in builds]

    deleted = _delete_builds(ids, db_url)
    return {"deleted": deleted, "ids": ids}
