"""Phase 5 — Reference Distribution API (M71/M72/M73)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from osfabricum.db.session import sync_session
from osfabricum.refdist import service as svc

router = APIRouter(prefix="/v1", tags=["refdist"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/refdist")
def list_reference_distributions(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        return [r.__dict__ for r in svc.list_reference_distributions(s)]


@router.get("/refdist/{name}")
def get_reference_distribution(name: str, req: Request) -> dict:
    with sync_session(_db(req)) as s:
        result = svc.get_reference_distribution(s, name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Reference distribution '{name}' not found")
    return result.__dict__


@router.get("/refdist/{name}/profiles")
def list_reference_profiles(name: str, req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = svc.list_reference_profiles(s, name)
    if not profiles:
        raise HTTPException(status_code=404, detail=f"No profiles found for '{name}'")
    return [p.__dict__ for p in profiles]


@router.get("/refdist/{name}/validate")
def validate_reference_distribution(name: str, req: Request) -> dict:
    with sync_session(_db(req)) as s:
        return svc.validate_reference_distribution(s, name)
