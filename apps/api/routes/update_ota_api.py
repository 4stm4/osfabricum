"""Update / OTA / Recovery Designer API (M49).

    GET  /v1/update-strategy-kinds
    GET  /v1/update-profiles
    POST /v1/update-profiles
    GET  /v1/update-profiles/{profile_id}
    PATCH /v1/update-profiles/{profile_id}
    POST /v1/update-profiles/{profile_id}/channels
    GET  /v1/update-profiles/{profile_id}/channels
    POST /v1/update-profiles/{profile_id}/recovery-targets
    GET  /v1/update-profiles/{profile_id}/recovery-targets
    POST /v1/update-profiles/{profile_id}/hooks
    GET  /v1/update-profiles/{profile_id}/hooks
    POST /v1/update-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import updates as upd
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["updates"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _profile_dict(p: object) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "description": p.description,
        "strategy": p.strategy,
        "signing_required": p.signing_required,
        "rollback_enabled": p.rollback_enabled,
        "rollback_window_days": p.rollback_window_days,
        "max_delta_size_mb": p.max_delta_size_mb,
        "verification_mode": p.verification_mode,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Strategy kinds
# ---------------------------------------------------------------------------


@router.get("/v1/update-strategy-kinds")
def list_update_strategy_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        return [
            {
                "kind": k.kind,
                "label": k.label,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in upd.list_update_strategy_kinds(s)
        ]


# ---------------------------------------------------------------------------
# Update profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    strategy: str = "full"
    distribution_id: str | None = None
    description: str = ""
    signing_required: bool = True
    rollback_enabled: bool = True
    rollback_window_days: int = 30
    max_delta_size_mb: int | None = None
    verification_mode: str = "strict"


class UpdateProfileBody(BaseModel):
    name: str | None = None
    description: str | None = None
    strategy: str | None = None
    signing_required: bool | None = None
    rollback_enabled: bool | None = None
    rollback_window_days: int | None = None
    max_delta_size_mb: int | None = None
    verification_mode: str | None = None


@router.get("/v1/update-profiles")
def list_update_profiles(
    req: Request, distribution_id: str | None = None
) -> list[dict]:
    with sync_session(_db(req)) as s:
        return [_profile_dict(p) for p in upd.list_update_profiles(s, distribution_id)]


@router.post("/v1/update-profiles")
def create_update_profile(
    body: CreateProfileBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = upd.create_update_profile(
                s,
                name=body.name,
                strategy=body.strategy,
                distribution_id=body.distribution_id,
                description=body.description,
                signing_required=body.signing_required,
                rollback_enabled=body.rollback_enabled,
                rollback_window_days=body.rollback_window_days,
                max_delta_size_mb=body.max_delta_size_mb,
                verification_mode=body.verification_mode,
            )
            s.commit()
            return _profile_dict(p)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/update-profiles/{profile_id}")
def get_update_profile(profile_id: str, req: Request) -> dict:
    with sync_session(_db(req)) as s:
        try:
            return _profile_dict(upd.get_update_profile(s, profile_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/update-profiles/{profile_id}")
def patch_update_profile(
    profile_id: str, body: UpdateProfileBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    with sync_session(_db(req)) as s:
        try:
            p = upd.update_update_profile(s, profile_id, **updates)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Update channels
# ---------------------------------------------------------------------------


class ChannelBody(BaseModel):
    name: str
    priority: int = 0
    url: str | None = None
    signing_key_id: str | None = None
    is_default: bool = False


@router.post("/v1/update-profiles/{profile_id}/channels")
def add_update_channel(
    profile_id: str, body: ChannelBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            ch = upd.add_update_channel(
                s, profile_id, body.name, body.priority,
                body.url, body.signing_key_id, body.is_default,
            )
            s.commit()
            return {
                "id": ch.id, "profile_id": ch.profile_id, "name": ch.name,
                "url": ch.url, "signing_key_id": ch.signing_key_id,
                "priority": ch.priority, "is_default": ch.is_default,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/update-profiles/{profile_id}/channels")
def list_update_channels(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": ch.id, "profile_id": ch.profile_id, "name": ch.name,
                    "url": ch.url, "signing_key_id": ch.signing_key_id,
                    "priority": ch.priority, "is_default": ch.is_default,
                }
                for ch in upd.list_update_channels(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Recovery targets
# ---------------------------------------------------------------------------


class RecoveryTargetBody(BaseModel):
    name: str
    target_type: str = "minimal"
    kernel_args: str | None = None
    initramfs_hint: str | None = None
    is_default: bool = False
    priority: int = 0


@router.post("/v1/update-profiles/{profile_id}/recovery-targets")
def add_recovery_target(
    profile_id: str, body: RecoveryTargetBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            t = upd.add_recovery_target(
                s, profile_id, body.name, body.target_type,
                body.kernel_args, body.initramfs_hint,
                body.is_default, body.priority,
            )
            s.commit()
            return {
                "id": t.id, "profile_id": t.profile_id, "name": t.name,
                "target_type": t.target_type, "kernel_args": t.kernel_args,
                "initramfs_hint": t.initramfs_hint,
                "is_default": t.is_default, "priority": t.priority,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/update-profiles/{profile_id}/recovery-targets")
def list_recovery_targets(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": t.id, "profile_id": t.profile_id, "name": t.name,
                    "target_type": t.target_type, "kernel_args": t.kernel_args,
                    "initramfs_hint": t.initramfs_hint,
                    "is_default": t.is_default, "priority": t.priority,
                }
                for t in upd.list_recovery_targets(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Update hooks
# ---------------------------------------------------------------------------


class HookBody(BaseModel):
    hook_point: str
    script_content: str
    priority: int = 0
    is_enabled: bool = True


@router.post("/v1/update-profiles/{profile_id}/hooks")
def add_update_hook(
    profile_id: str, body: HookBody, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            h = upd.add_update_hook(
                s, profile_id, body.hook_point, body.script_content,
                body.priority, body.is_enabled,
            )
            s.commit()
            return {
                "id": h.id, "profile_id": h.profile_id,
                "hook_point": h.hook_point,
                "script_content": h.script_content,
                "priority": h.priority, "is_enabled": h.is_enabled,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/update-profiles/{profile_id}/hooks")
def list_update_hooks(profile_id: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [
                {
                    "id": h.id, "profile_id": h.profile_id,
                    "hook_point": h.hook_point,
                    "script_content": h.script_content,
                    "priority": h.priority, "is_enabled": h.is_enabled,
                }
                for h in upd.list_update_hooks(s, profile_id)
            ]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/update-profiles/{profile_id}/render")
def render_update_config(
    profile_id: str, req: Request, _auth: WriteAuthDep = None
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = upd.render_update_config(s, profile_id)
            s.commit()
            return {
                "id": p.id,
                "content_hash": p.content_hash,
                "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
                "rendered_update_config": p.rendered_update_config,
                "rendered_recovery_config": p.rendered_recovery_config,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
