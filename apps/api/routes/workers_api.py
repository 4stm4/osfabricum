"""REST API routes for workers (M20).

GET /v1/workers     — list registered workers
GET /v1/workers/{hostname}  — single worker detail
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from osfabricum.db.models import Worker
from osfabricum.db.session import sync_session

router = APIRouter(prefix="/v1/workers", tags=["workers"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url
    except AttributeError:
        return None


class WorkerItem(BaseModel):
    id: str
    hostname: str
    enabled: bool
    kinds: list[str]
    tags: list[str]
    last_seen_at: str | None


@router.get("", response_model=list[WorkerItem])
def list_workers(request: Request) -> list[WorkerItem]:
    """List all registered workers."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        workers = session.scalars(select(Worker).order_by(Worker.hostname)).all()
        return [
            WorkerItem(
                id=w.id,
                hostname=w.hostname,
                enabled=w.enabled,
                kinds=list(w.kinds_json or []),
                tags=list(w.tags_json or []),
                last_seen_at=w.last_seen_at.isoformat() if w.last_seen_at else None,
            )
            for w in workers
        ]


@router.get("/{hostname}", response_model=WorkerItem)
def get_worker(hostname: str, request: Request) -> WorkerItem:
    """Return details for a single worker by hostname."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        w = session.scalar(select(Worker).where(Worker.hostname == hostname))
        if w is None:
            raise HTTPException(status_code=404, detail=f"Worker {hostname!r} not found")
        return WorkerItem(
            id=w.id,
            hostname=w.hostname,
            enabled=w.enabled,
            kinds=list(w.kinds_json or []),
            tags=list(w.tags_json or []),
            last_seen_at=w.last_seen_at.isoformat() if w.last_seen_at else None,
        )
