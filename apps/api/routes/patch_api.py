"""M56 — Patch Queue / Source Patch Manager API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import patches
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["patches"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


@router.get("/patch-target-kinds")
def list_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = patches.list_patch_target_kinds(s)
    return [{"kind": k.kind, "label": k.label, "description": k.description,
              "display_order": k.display_order} for k in kinds]


@router.get("/patch-sets")
def list_patch_sets(req: Request, distribution_id: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        pss = patches.list_patch_sets(s, distribution_id)
    return [_ps_dict(ps) for ps in pss]


@router.post("/patch-sets", dependencies=[require_write_auth])
def create_patch_set(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            ps = patches.create_patch_set(
                s, name=body["name"],
                distribution_id=body.get("distribution_id"),
                description=body.get("description", ""),
                target_kind=body.get("target_kind", "kernel"),
            )
            s.commit()
            return _ps_dict(ps)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/patch-sets/{ps_id}")
def get_patch_set(req: Request, ps_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            return _ps_dict(patches.get_patch_set(s, ps_id))
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/patch-sets/{ps_id}", dependencies=[require_write_auth])
def update_patch_set(req: Request, ps_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            ps = patches.update_patch_set(s, ps_id, **body)
            s.commit()
            return _ps_dict(ps)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(
                status_code=404 if isinstance(exc, KeyError) else 400,
                detail=str(exc),
            ) from exc


@router.get("/patch-sets/{ps_id}/patches")
def list_patches(req: Request, ps_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [_patch_dict(p) for p in patches.list_patches(s, ps_id)]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/patch-sets/{ps_id}/patches", dependencies=[require_write_auth])
def add_patch(req: Request, ps_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = patches.add_patch(
                s, ps_id,
                sequence_num=body["sequence_num"],
                name=body["name"],
                patch_content=body.get("patch_content", ""),
                patch_format=body.get("patch_format", "diff"),
                is_enabled=body.get("is_enabled", True),
                description=body.get("description", ""),
            )
            s.commit()
            return _patch_dict(p)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(
                status_code=404 if isinstance(exc, KeyError) else 400,
                detail=str(exc),
            ) from exc


@router.post("/patch-sets/{ps_id}/render", dependencies=[require_write_auth])
def render(req: Request, ps_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            ps = patches.render_patch_manifest(s, ps_id)
            s.commit()
            return {"id": ps.id, "content_hash": ps.content_hash,
                    "rendered_patch_manifest": ps.rendered_patch_manifest,
                    "rendered_at": ps.rendered_at.isoformat() if ps.rendered_at else None}
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/patch-sets/{ps_id}/apply", dependencies=[require_write_auth])
def apply_patch_set(req: Request, ps_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            result = patches.record_application(
                s, ps_id,
                status=body.get("status", "success"),
                applied_count=body.get("applied_count", 0),
                failed_at_sequence=body.get("failed_at_sequence"),
                error_message=body.get("error_message"),
            )
            s.commit()
            return _result_dict(result)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(
                status_code=404 if isinstance(exc, KeyError) else 400,
                detail=str(exc),
            ) from exc


@router.get("/patch-sets/{ps_id}/apply")
def list_results(req: Request, ps_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            return [_result_dict(r) for r in patches.list_application_results(s, ps_id)]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _ps_dict(ps: object) -> dict:
    return {"id": ps.id, "name": ps.name, "distribution_id": ps.distribution_id,
            "description": ps.description, "target_kind": ps.target_kind,
            "content_hash": ps.content_hash,
            "rendered_at": ps.rendered_at.isoformat() if ps.rendered_at else None,
            "created_at": ps.created_at.isoformat(), "updated_at": ps.updated_at.isoformat()}


def _patch_dict(p: object) -> dict:
    return {"id": p.id, "patch_set_id": p.patch_set_id, "sequence_num": p.sequence_num,
            "name": p.name, "patch_format": p.patch_format, "is_enabled": p.is_enabled,
            "description": p.description,
            "patch_content_length": len(p.patch_content)}


def _result_dict(r: object) -> dict:
    return {"id": r.id, "patch_set_id": r.patch_set_id,
            "applied_at": r.applied_at.isoformat(),
            "status": r.status, "applied_count": r.applied_count,
            "failed_at_sequence": r.failed_at_sequence,
            "error_message": r.error_message}
