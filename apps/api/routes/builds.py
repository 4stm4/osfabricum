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
    """List builds with optional filters."""
    db_url = _get_db_url(request)
    builds = search_builds(
        distribution_name=distribution,
        status=status,
        board_id=board_id,
        limit=limit,
        db_url=db_url,
    )
    return [
        BuildListItem(
            id=b.id,
            distribution_id=b.distribution_id,
            profile_id=b.profile_id,
            board_id=b.board_id,
            status=b.status,
            created_at=b.created_at.isoformat() if b.created_at else None,
        )
        for b in builds
    ]


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
def cancel_build_api(build_id: str, request: Request) -> dict[str, str]:
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
