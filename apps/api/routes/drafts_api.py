"""Build Wizard draft API (M28).

    GET    /v1/build-drafts
    POST   /v1/build-drafts
    GET    /v1/build-drafts/{id}
    PATCH  /v1/build-drafts/{id}
    DELETE /v1/build-drafts/{id}

A draft is a resumable wizard session. Submitting a build still goes through
``POST /v1/builds`` (M29).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from osfabricum import orchestrator

router = APIRouter(prefix="/v1/build-drafts", tags=["build-drafts"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


class DraftCreate(BaseModel):
    name: str | None = None
    source_kind: str = "new"
    distribution: str | None = None
    profile: str | None = None
    board: str | None = None
    overrides: dict[str, Any] | None = None


class DraftUpdate(BaseModel):
    name: str | None = None
    distribution: str | None = None
    profile: str | None = None
    board: str | None = None
    overrides: dict[str, Any] | None = None
    status: str | None = None


@router.get("")
def list_drafts(request: Request) -> list[dict[str, Any]]:
    return orchestrator.list_drafts(db_url=_db(request))


@router.post("", status_code=201)
def create_draft(body: DraftCreate, request: Request) -> dict[str, Any]:
    return orchestrator.create_draft(
        name=body.name,
        source_kind=body.source_kind,
        distribution=body.distribution,
        profile=body.profile,
        board=body.board,
        overrides=body.overrides,
        db_url=_db(request),
    )


@router.get("/{draft_id}")
def get_draft(draft_id: str, request: Request) -> dict[str, Any]:
    try:
        return orchestrator.get_draft(draft_id, db_url=_db(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{draft_id}")
def update_draft(draft_id: str, body: DraftUpdate, request: Request) -> dict[str, Any]:
    provided = body.model_fields_set
    kwargs: dict[str, Any] = {k: getattr(body, k) for k in provided}
    try:
        return orchestrator.update_draft(draft_id, db_url=_db(request), **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: str, request: Request) -> Response:
    try:
        orchestrator.delete_draft(draft_id, db_url=_db(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
