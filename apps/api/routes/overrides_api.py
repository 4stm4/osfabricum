"""M55 — Override / Masking engine API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import overrides
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["overrides"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


@router.get("/override-kinds")
def list_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = overrides.list_override_kinds(s)
    return [{"kind": k.kind, "label": k.label, "description": k.description,
              "display_order": k.display_order} for k in kinds]


@router.get("/override-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = overrides.list_override_profiles(s, distribution_id)
    return [_profile_dict(p) for p in profiles]


@router.post("/override-profiles", dependencies=[require_write_auth])
def create_profile(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = overrides.create_override_profile(
                s, name=body["name"],
                distribution_id=body.get("distribution_id"),
                description=body.get("description", ""),
            )
            s.commit()
            return _profile_dict(p)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/override-profiles/{profile_id}")
def get_profile(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            return _profile_dict(overrides.get_override_profile(s, profile_id))
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/override-profiles/{profile_id}", dependencies=[require_write_auth])
def update_profile(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = overrides.update_override_profile(s, profile_id, **body)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/override-profiles/{profile_id}/rules")
def list_rules(req: Request, profile_id: str, target_type: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [_rule_dict(r) for r in
                    overrides.list_override_rules(s, profile_id, target_type)]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/override-profiles/{profile_id}/rules", dependencies=[require_write_auth])
def add_rule(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = overrides.add_override_rule(
                s, profile_id,
                target_type=body["target_type"],
                target_key=body["target_key"],
                action=body.get("action", "set"),
                value=body.get("value"),
                reason=body.get("reason", ""),
                priority=body.get("priority", 0),
            )
            s.commit()
            return _rule_dict(r)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/override-profiles/{profile_id}/render", dependencies=[require_write_auth])
def render(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = overrides.render_override_policy(s, profile_id)
            s.commit()
            return {"id": p.id, "content_hash": p.content_hash,
                    "rendered_override_policy": p.rendered_override_policy,
                    "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None}
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _profile_dict(p: object) -> dict:
    return {"id": p.id, "name": p.name, "distribution_id": p.distribution_id,
            "description": p.description, "content_hash": p.content_hash,
            "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
            "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat()}


def _rule_dict(r: object) -> dict:
    return {"id": r.id, "profile_id": r.profile_id, "target_type": r.target_type,
            "target_key": r.target_key, "action": r.action, "value": r.value,
            "reason": r.reason, "priority": r.priority}
