"""M66 — Boot / Performance Profiler API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import bootprofiler as bp_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["bootprofiler"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/builds/{build_id}/boot-profile")
def get_boot_profiles(req: Request, build_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = bp_svc.list_boot_profiles(s, build_id)
    return [_bp_dict(p) for p in profiles]


@router.post("/builds/{build_id}/boot-profile", dependencies=[require_write_auth])
def create_boot_profile(req: Request, build_id: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        try:
            p = bp_svc.create_boot_profile(
                s, build_id=build_id,
                capture_method=b.get("capture_method", "qemu"),
            )
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _bp_dict(p)


@router.get("/boot-profiles/{profile_id}")
def get_boot_profile(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = bp_svc.get_boot_profile(s, profile_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _bp_dict(p, include_rendered=True)


@router.post("/boot-profiles/{profile_id}/samples", dependencies=[require_write_auth])
def add_sample(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            s_obj = bp_svc.add_boot_sample(
                s, boot_profile_id=profile_id,
                event_kind=body["event_kind"],
                event_name=body["event_name"],
                timestamp_ms=body["timestamp_ms"],
                duration_ms=body.get("duration_ms"),
                is_critical_path=body.get("is_critical_path", False),
            )
            s.commit()
            s.refresh(s_obj)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": s_obj.id, "boot_profile_id": s_obj.boot_profile_id,
        "event_kind": s_obj.event_kind, "event_name": s_obj.event_name,
        "timestamp_ms": s_obj.timestamp_ms, "duration_ms": s_obj.duration_ms,
        "is_critical_path": s_obj.is_critical_path,
    }


@router.post("/boot-profiles/{profile_id}/render", dependencies=[require_write_auth])
def render_timeline(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = bp_svc.render_boot_timeline(s, profile_id)
            s.commit()
            s.refresh(p)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _bp_dict(p, include_rendered=True)


def _bp_dict(p, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": p.id, "build_id": p.build_id, "capture_method": p.capture_method,
        "total_boot_ms": p.total_boot_ms, "content_hash": p.content_hash,
        "summary_json": p.summary_json,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
    if include_rendered:
        d["rendered_timeline"] = p.rendered_timeline
    return d
