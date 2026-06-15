"""M60 — System Generations / Rollback Designer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import generations as gen_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["generations"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/rollback-kinds")
def list_rollback_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = gen_svc.list_rollback_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.get("/generations")
def list_generations(
    req: Request,
    distribution_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        gens = gen_svc.list_generations(s, distribution_id, status)
    return [_gen_dict(g) for g in gens]


@router.post("/generations", dependencies=[require_write_auth])
def create_generation(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            g = gen_svc.create_generation(
                s,
                distribution_id=body["distribution_id"],
                generation_number=body["generation_number"],
                description=body.get("description", ""),
                release_id=body.get("release_id"),
                status=body.get("status", "active"),
            )
            s.commit()
            s.refresh(g)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _gen_dict(g)


@router.get("/generations/{generation_id}")
def get_generation(req: Request, generation_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            g = gen_svc.get_generation(s, generation_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _gen_dict(g)


@router.patch("/generations/{generation_id}", dependencies=[require_write_auth])
def update_generation(req: Request, generation_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            g = gen_svc.update_generation(
                s, generation_id,
                status=body.get("status"),
                description=body.get("description"),
            )
            s.commit()
            s.refresh(g)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _gen_dict(g)


@router.put("/generations/{generation_id}/artifacts", dependencies=[require_write_auth])
def add_generation_artifact(req: Request, generation_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            a = gen_svc.add_generation_artifact(
                s, generation_id,
                artifact_role=body["artifact_role"],
                artifact_id=body.get("artifact_id"),
                artifact_uri=body.get("artifact_uri"),
            )
            s.commit()
            s.refresh(a)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": a.id, "generation_id": a.generation_id,
        "artifact_role": a.artifact_role, "artifact_id": a.artifact_id,
        "artifact_uri": a.artifact_uri,
    }


@router.put(
    "/generations/{generation_id}/rollback-targets",
    dependencies=[require_write_auth],
)
def add_rollback_target(req: Request, generation_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            t = gen_svc.add_rollback_target(
                s, generation_id,
                target_generation_number=body["target_generation_number"],
                rollback_kind=body.get("rollback_kind", "full"),
                priority=body.get("priority", 0),
            )
            s.commit()
            s.refresh(t)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": t.id, "generation_id": t.generation_id,
        "target_generation_number": t.target_generation_number,
        "rollback_kind": t.rollback_kind, "priority": t.priority,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("/generations/{generation_id}/render", dependencies=[require_write_auth])
def render_generation_manifest(req: Request, generation_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            g = gen_svc.render_generation_manifest(s, generation_id)
            s.commit()
            s.refresh(g)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _gen_dict(g, include_rendered=True)


@router.post(
    "/generations/{generation_id}/rollback-plan",
    dependencies=[require_write_auth],
)
def render_rollback_plan(req: Request, generation_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            t = gen_svc.render_rollback_plan(
                s, generation_id,
                target_generation_number=body["target_generation_number"],
            )
            s.commit()
            s.refresh(t)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": t.id, "generation_id": t.generation_id,
        "target_generation_number": t.target_generation_number,
        "rollback_kind": t.rollback_kind, "priority": t.priority,
        "rendered_rollback_plan": t.rendered_rollback_plan,
    }


def _gen_dict(g, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": g.id,
        "distribution_id": g.distribution_id,
        "release_id": g.release_id,
        "generation_number": g.generation_number,
        "status": g.status,
        "description": g.description,
        "content_hash": g.content_hash,
        "rendered_at": g.rendered_at.isoformat() if g.rendered_at else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }
    if include_rendered:
        d["rendered_generation_manifest"] = g.rendered_generation_manifest
    return d
