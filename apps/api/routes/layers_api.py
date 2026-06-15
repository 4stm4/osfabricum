"""M54 — OS Composition Layers designer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import layers
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["layers"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


@router.get("/layer-kinds")
def list_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = layers.list_layer_kinds(s)
    return [{"kind": k.kind, "label": k.label, "description": k.description,
              "display_order": k.display_order} for k in kinds]


@router.get("/layer-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = layers.list_layer_profiles(s, distribution_id)
    return [_profile_dict(p) for p in profiles]


@router.post("/layer-profiles", dependencies=[require_write_auth])
def create_profile(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = layers.create_layer_profile(
                s, name=body["name"],
                distribution_id=body.get("distribution_id"),
                description=body.get("description", ""),
                base_layer=body.get("base_layer", "base"),
            )
            s.commit()
            return _profile_dict(p)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/layer-profiles/{profile_id}")
def get_profile(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            return _profile_dict(layers.get_layer_profile(s, profile_id))
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/layer-profiles/{profile_id}", dependencies=[require_write_auth])
def update_profile(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = layers.update_layer_profile(s, profile_id, **body)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/layer-profiles/{profile_id}/entries")
def list_entries(req: Request, profile_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [_entry_dict(e) for e in layers.list_layer_entries(s, profile_id)]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/layer-profiles/{profile_id}/entries", dependencies=[require_write_auth])
def add_entry(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            e = layers.add_layer_entry(
                s, profile_id,
                name=body["name"],
                layer_kind=body.get("layer_kind", "extension"),
                source_url=body.get("source_url"),
                sha256_hint=body.get("sha256_hint"),
                priority=body.get("priority", 0),
                is_enabled=body.get("is_enabled", True),
                description=body.get("description", ""),
            )
            s.commit()
            return _entry_dict(e)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/layer-profiles/{profile_id}/render", dependencies=[require_write_auth])
def render(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = layers.render_layer_manifest(s, profile_id)
            s.commit()
            return {"id": p.id, "content_hash": p.content_hash,
                    "rendered_manifest": p.rendered_manifest,
                    "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None}
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _profile_dict(p: object) -> dict:
    return {"id": p.id, "name": p.name, "distribution_id": p.distribution_id,
            "description": p.description, "base_layer": p.base_layer,
            "content_hash": p.content_hash,
            "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
            "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat()}


def _entry_dict(e: object) -> dict:
    return {"id": e.id, "profile_id": e.profile_id, "name": e.name,
            "layer_kind": e.layer_kind, "source_url": e.source_url,
            "sha256_hint": e.sha256_hint, "priority": e.priority,
            "is_enabled": e.is_enabled, "description": e.description}
