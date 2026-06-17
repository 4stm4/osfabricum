"""M67 — Distributed Build Farm / Worker Pools API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import workerpool as wp_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["workerpool"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/worker-pools")
def list_worker_pools(
    req: Request, pool_kind: str | None = None
) -> list[dict]:
    with sync_session(_db(req)) as s:
        pools = wp_svc.list_worker_pools(s, pool_kind)
    return [_pool_dict(p) for p in pools]


@router.post("/worker-pools", dependencies=[require_write_auth])
def create_worker_pool(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = wp_svc.create_worker_pool(
                s, name=body["name"],
                pool_kind=body.get("pool_kind", "local"),
                label=body.get("label", ""),
                description=body.get("description", ""),
                max_parallelism=body.get("max_parallelism", 1),
            )
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _pool_dict(p)


@router.get("/worker-pools/{pool_id}")
def get_worker_pool(req: Request, pool_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = wp_svc.get_worker_pool(s, pool_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _pool_dict(p)


@router.patch("/worker-pools/{pool_id}", dependencies=[require_write_auth])
def update_worker_pool(req: Request, pool_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = wp_svc.update_worker_pool(
                s, pool_id, label=body.get("label"),
                description=body.get("description"),
                max_parallelism=body.get("max_parallelism"),
                pool_kind=body.get("pool_kind"),
            )
            s.commit()
            s.refresh(p)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _pool_dict(p)


@router.post("/worker-pools/{pool_id}/members", dependencies=[require_write_auth])
def add_pool_member(req: Request, pool_id: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        m = wp_svc.add_pool_member(s, pool_id, worker_id=b.get("worker_id"))
        s.commit()
        s.refresh(m)
    return {
        "id": m.id, "worker_pool_id": m.worker_pool_id,
        "worker_id": m.worker_id,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    }


@router.post("/worker-pools/{pool_id}/affinities", dependencies=[require_write_auth])
def add_affinity(req: Request, pool_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        a = wp_svc.add_job_affinity(
            s, pool_id, job_kind=body["job_kind"],
            weight=body.get("affinity_weight", 1),
        )
        s.commit()
        s.refresh(a)
    return {
        "id": a.id, "pool_id": a.pool_id,
        "job_kind": a.job_kind, "affinity_weight": a.affinity_weight,
    }


@router.post("/worker-pools/{pool_id}/quotas", dependencies=[require_write_auth])
def set_quota(req: Request, pool_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            q = wp_svc.set_pool_quota(
                s, pool_id,
                resource_kind=body["resource_kind"],
                limit_value=body["limit_value"],
                period_seconds=body.get("period_seconds", 3600),
            )
            s.commit()
            s.refresh(q)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": q.id, "pool_id": q.pool_id,
        "resource_kind": q.resource_kind,
        "limit_value": q.limit_value, "period_seconds": q.period_seconds,
    }


def _pool_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "label": p.label, "pool_kind": p.pool_kind,
        "max_parallelism": p.max_parallelism,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
