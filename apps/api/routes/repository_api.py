"""M69 — Public Artifact Repository / Release Publishing API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import repository as repo_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["repository"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/release-channels")
def list_channels(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        channels = repo_svc.list_release_channels(s)
    return [
        {"channel": c.channel, "label": c.label, "description": c.description,
         "display_order": c.display_order}
        for c in channels
    ]


@router.get("/repositories")
def list_repositories(req: Request, repo_kind: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        repos = repo_svc.list_repositories(s, repo_kind)
    return [_repo_dict(r) for r in repos]


@router.post("/repositories", dependencies=[require_write_auth])
def create_repository(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = repo_svc.create_repository(
                s, name=body["name"],
                repo_kind=body.get("repo_kind", "image"),
                label=body.get("label", ""),
                description=body.get("description", ""),
                base_url=body.get("base_url"),
                sign_key_id=body.get("sign_key_id"),
            )
            s.commit()
            s.refresh(r)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _repo_dict(r)


@router.get("/repositories/{repo_id}")
def get_repository(req: Request, repo_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = repo_svc.get_repository(s, repo_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _repo_dict(r)


@router.post("/repositories/{repo_id}/index", dependencies=[require_write_auth])
def index_repository(req: Request, repo_id: str, body: dict | None = None) -> dict:
    b = body or {}
    channel = b.get("channel", "stable")
    with sync_session(_db(req)) as s:
        try:
            idx = repo_svc.index_repository(s, repo_id, channel)
            s.commit()
            s.refresh(idx)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": idx.id, "repository_id": idx.repository_id,
        "channel": idx.channel, "content_hash": idx.content_hash,
        "indexed_at": idx.indexed_at.isoformat() if idx.indexed_at else None,
        "rendered_index": idx.rendered_index,
    }


@router.get("/releases")
def list_releases(
    req: Request,
    channel: str | None = None,
    status: str | None = None,
    distribution_id: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        rels = repo_svc.list_releases(s, channel, status, distribution_id)
    return [_rel_dict(r) for r in rels]


@router.post("/releases", dependencies=[require_write_auth])
def create_release(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        r = repo_svc.create_release(
            s, channel=body["channel"], version=body["version"],
            distribution_id=body.get("distribution_id"),
        )
        s.commit()
        s.refresh(r)
    return _rel_dict(r)


@router.get("/releases/{release_id}")
def get_release(req: Request, release_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = repo_svc.get_release(s, release_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _rel_dict(r, include_rendered=True)


@router.post("/releases/{release_id}/publish", dependencies=[require_write_auth])
def publish_release(req: Request, release_id: str, body: dict | None = None) -> dict:
    status = (body or {}).get("status", "published")
    with sync_session(_db(req)) as s:
        try:
            r = repo_svc.promote_release(s, release_id, status)
            s.commit()
            s.refresh(r)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _rel_dict(r)


@router.put("/releases/{release_id}/artifacts", dependencies=[require_write_auth])
def add_release_artifact(req: Request, release_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            a = repo_svc.add_release_artifact(
                s, release_id,
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
        "id": a.id, "release_id": a.release_id,
        "artifact_role": a.artifact_role, "artifact_uri": a.artifact_uri,
    }


@router.post("/releases/{release_id}/render", dependencies=[require_write_auth])
def render_release(req: Request, release_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = repo_svc.render_release_manifest(s, release_id)
            s.commit()
            s.refresh(r)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _rel_dict(r, include_rendered=True)


def _repo_dict(r) -> dict:
    return {
        "id": r.id, "name": r.name, "label": r.label,
        "repo_kind": r.repo_kind, "base_url": r.base_url,
        "is_published": r.is_published,
    }


def _rel_dict(r, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": r.id, "channel": r.channel, "version": r.version,
        "status": r.status, "distribution_id": r.distribution_id,
        "content_hash": r.content_hash,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if include_rendered:
        d["rendered_release_manifest"] = r.rendered_release_manifest
    return d
