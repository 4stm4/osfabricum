"""M62 — Manifest / Lockfile System API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import lockfile as lf_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["lockfile"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/lockfiles")
def list_lockfiles(
    req: Request,
    distribution_id: str | None = None,
    build_id: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        lfs = lf_svc.list_lockfiles(s, distribution_id, build_id)
    return [_lf_dict(l) for l in lfs]


@router.post("/plan/lock", dependencies=[require_write_auth])
def create_lockfile(req: Request, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        lf = lf_svc.create_lockfile(
            s,
            distribution_id=b.get("distribution_id"),
            profile_id=b.get("profile_id"),
            build_id=b.get("build_id"),
            lock_version=b.get("lock_version", "1"),
        )
        s.commit()
        s.refresh(lf)
    return _lf_dict(lf)


@router.get("/lockfiles/{lockfile_id}")
def get_lockfile(req: Request, lockfile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            lf = lf_svc.get_lockfile(s, lockfile_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _lf_dict(lf, include_rendered=True)


@router.post("/lockfiles/{lockfile_id}/entries", dependencies=[require_write_auth])
def add_entry(req: Request, lockfile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            e = lf_svc.add_lockfile_entry(
                s, lockfile_id,
                entry_kind=body["entry_kind"],
                entry_key=body["entry_key"],
                version=body.get("version", ""),
                source_hash=body.get("source_hash"),
                extra_json=body.get("extra_json"),
            )
            s.commit()
            s.refresh(e)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return {
        "id": e.id, "lockfile_id": e.lockfile_id,
        "entry_kind": e.entry_kind, "entry_key": e.entry_key,
        "version": e.version, "source_hash": e.source_hash,
    }


@router.post("/lockfiles/{lockfile_id}/render", dependencies=[require_write_auth])
def render_lockfile(req: Request, lockfile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            lf = lf_svc.render_lockfile(s, lockfile_id)
            s.commit()
            s.refresh(lf)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _lf_dict(lf, include_rendered=True)


@router.post("/lock/diff")
def diff_lockfiles(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            result = lf_svc.diff_lockfiles(s, body["lockfile_a_id"], body["lockfile_b_id"])
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return result


def _lf_dict(lf, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": lf.id, "distribution_id": lf.distribution_id,
        "profile_id": lf.profile_id, "build_id": lf.build_id,
        "lock_version": lf.lock_version, "content_hash": lf.content_hash,
        "created_at": lf.created_at.isoformat() if lf.created_at else None,
    }
    if include_rendered:
        d["rendered_lock"] = lf.rendered_lock
    return d
