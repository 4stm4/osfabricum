"""M61 — Attended Upgrade / Rebuild Service API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import upgrade as upg_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["upgrade"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/upgrades")
def list_upgrades(
    req: Request,
    distribution_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        reqs = upg_svc.list_upgrade_requests(s, distribution_id, status)
    return [_req_dict(r) for r in reqs]


@router.post("/upgrades", dependencies=[require_write_auth])
def create_upgrade(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        r = upg_svc.create_upgrade_request(
            s,
            distribution_id=body.get("distribution_id"),
            profile_id=body.get("profile_id"),
            current_generation_id=body.get("current_generation_id"),
            target_channel=body.get("target_channel", "stable"),
            target_version=body.get("target_version"),
        )
        s.commit()
        s.refresh(r)
    return _req_dict(r)


@router.get("/upgrades/{upgrade_id}")
def get_upgrade(req: Request, upgrade_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = upg_svc.get_upgrade_request(s, upgrade_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _req_dict(r)


@router.patch("/upgrades/{upgrade_id}", dependencies=[require_write_auth])
def update_upgrade(req: Request, upgrade_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = upg_svc.update_upgrade_status(s, upgrade_id, body["status"])
            s.commit()
            s.refresh(r)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _req_dict(r)


@router.post("/upgrades/{upgrade_id}/result", dependencies=[require_write_auth])
def record_result(req: Request, upgrade_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            res = upg_svc.record_upgrade_result(
                s, upgrade_id,
                status=body["status"],
                new_generation_id=body.get("new_generation_id"),
                artifact_id=body.get("artifact_id"),
                diff_report_id=body.get("diff_report_id"),
                error_message=body.get("error_message"),
            )
            s.commit()
            s.refresh(res)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": res.id, "upgrade_id": res.upgrade_id, "status": res.status,
        "new_generation_id": res.new_generation_id,
        "created_at": res.created_at.isoformat() if res.created_at else None,
    }


def _req_dict(r) -> dict:
    return {
        "id": r.id, "distribution_id": r.distribution_id,
        "profile_id": r.profile_id, "status": r.status,
        "target_channel": r.target_channel, "target_version": r.target_version,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }
