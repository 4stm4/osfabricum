"""M50 — SDK / dev-shell export designer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import sdk
from osfabricum.db.session import sync_session
from osfabricum.security.auth import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["sdk"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


# ---------------------------------------------------------------------------
# Export kinds (read-only)
# ---------------------------------------------------------------------------


@router.get("/sdk-export-kinds")
def list_export_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = sdk.list_sdk_export_kinds(s)
    return [
        {
            "kind": k.kind,
            "label": k.label,
            "description": k.description,
            "display_order": k.display_order,
        }
        for k in kinds
    ]


# ---------------------------------------------------------------------------
# SDK profiles
# ---------------------------------------------------------------------------


@router.get("/sdk-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = sdk.list_sdk_profiles(s, distribution_id)
    return [_profile_dict(p) for p in profiles]


@router.post("/sdk-profiles", dependencies=[WriteAuthDep])
def create_profile(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = sdk.create_sdk_profile(
                s,
                name=body["name"],
                export_format=body.get("export_format", "shell-env"),
                distribution_id=body.get("distribution_id"),
                description=body.get("description", ""),
                python_version=body.get("python_version", "3.11"),
                include_debug_symbols=body.get("include_debug_symbols", False),
            )
            s.commit()
            return _profile_dict(p)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sdk-profiles/{profile_id}")
def get_profile(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = sdk.get_sdk_profile(s, profile_id)
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/sdk-profiles/{profile_id}", dependencies=[WriteAuthDep])
def update_profile(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = sdk.update_sdk_profile(s, profile_id, **body)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# SDK variables
# ---------------------------------------------------------------------------


@router.get("/sdk-profiles/{profile_id}/variables")
def list_variables(req: Request, profile_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            variables = sdk.list_sdk_variables(s, profile_id)
            return [_var_dict(v) for v in variables]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/sdk-profiles/{profile_id}/variables/{key}", dependencies=[WriteAuthDep])
def set_variable(req: Request, profile_id: str, key: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            v = sdk.set_sdk_variable(
                s,
                profile_id,
                key,
                value=body.get("value", ""),
                description=body.get("description", ""),
                is_secret=body.get("is_secret", False),
            )
            s.commit()
            return _var_dict(v)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/sdk-profiles/{profile_id}/render", dependencies=[WriteAuthDep])
def render(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = sdk.render_sdk_export(s, profile_id)
            s.commit()
            return {
                "id": p.id,
                "content_hash": p.content_hash,
                "rendered_setup_script": p.rendered_setup_script,
                "rendered_env_script": p.rendered_env_script,
                "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
            }
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_dict(p: object) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "description": p.description,
        "export_format": p.export_format,
        "python_version": p.python_version,
        "include_debug_symbols": p.include_debug_symbols,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _var_dict(v: object) -> dict:
    return {
        "id": v.id,
        "profile_id": v.profile_id,
        "key": v.key,
        "value": "****" if v.is_secret else v.value,
        "description": v.description,
        "is_secret": v.is_secret,
    }
