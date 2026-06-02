"""REST API route for build plan resolution (M20).

    GET /v1/plan?distribution=&profile=&board=  — resolve a build plan
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from osfabricum.resolver import resolve_plan

router = APIRouter(prefix="/v1/plan", tags=["plan"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url
    except AttributeError:
        return None


@router.get("")
def get_plan(
    request: Request,
    distribution: Annotated[str, Query(description="Distribution name")],
    profile: Annotated[str, Query(description="Profile name")],
    board: Annotated[str, Query(description="Board name")],
) -> dict[str, Any]:
    """Resolve and return a build plan without building."""
    db_url = _db(request)
    try:
        plan = resolve_plan(distribution, profile, board, db_url=db_url)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return plan.to_dict()
