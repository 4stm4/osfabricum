"""M68 — Build Isolation / Sandbox Policy API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import isolation as iso_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["isolation"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/isolation-policies")
def list_policies(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        policies = iso_svc.list_isolation_policies(s)
    return [_policy_dict(p) for p in policies]


@router.post("/isolation-policies", dependencies=[require_write_auth])
def create_policy(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = iso_svc.create_isolation_policy(
                s, name=body["name"],
                mode=body.get("mode", "none"),
                label=body.get("label", ""),
                description=body.get("description", ""),
                network_allowed=body.get("network_allowed", True),
                write_access=body.get("write_access", "build-dir"),
                cache_mode=body.get("cache_mode", "ro"),
                secret_access=body.get("secret_access", False),
                privileged=body.get("privileged", False),
            )
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _policy_dict(p)


@router.get("/isolation-policies/{policy_id}")
def get_policy(req: Request, policy_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = iso_svc.get_isolation_policy(s, policy_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _policy_dict(p)


@router.patch("/isolation-policies/{policy_id}", dependencies=[require_write_auth])
def update_policy(req: Request, policy_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = iso_svc.update_isolation_policy(
                s, policy_id,
                mode=body.get("mode"),
                network_allowed=body.get("network_allowed"),
                write_access=body.get("write_access"),
                cache_mode=body.get("cache_mode"),
                secret_access=body.get("secret_access"),
                privileged=body.get("privileged"),
            )
            s.commit()
            s.refresh(p)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _policy_dict(p)


@router.post("/isolation-policies/{policy_id}/requirements", dependencies=[require_write_auth])
def add_requirement(req: Request, policy_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = iso_svc.add_recipe_requirement(
                s, required_mode=body["required_mode"],
                recipe_id=body.get("recipe_id"),
                reason=body.get("reason", ""),
            )
            s.commit()
            s.refresh(r)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": r.id, "recipe_id": r.recipe_id,
        "required_mode": r.required_mode, "reason": r.reason,
    }


def _policy_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "label": p.label,
        "mode": p.mode, "network_allowed": p.network_allowed,
        "write_access": p.write_access, "cache_mode": p.cache_mode,
        "secret_access": p.secret_access, "privileged": p.privileged,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
