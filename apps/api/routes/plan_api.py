"""REST API for build plan resolution and prefetch (M20 + M29 write API).

GET  /v1/plan?distribution=&profile=&board=   — resolve a plan (read)
POST /v1/plan                                  — resolve with overrides
POST /v1/plan/validate                         — validity + missing report
POST /v1/plan/diff                             — diff two plans
POST /v1/prefetch                              — prefetch report for a plan
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from osfabricum import orchestrator
from osfabricum.resolver import resolve_plan

router = APIRouter(prefix="/v1/plan", tags=["plan"])
prefetch_router = APIRouter(prefix="/v1/prefetch", tags=["plan"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


class PlanRequest(BaseModel):
    distribution: str
    profile: str
    board: str
    overrides: dict[str, Any] | None = None


class PlanDiffRequest(BaseModel):
    distribution: str
    board: str
    a: dict[str, Any]
    b: dict[str, Any]


@router.get("")
def get_plan(
    request: Request,
    distribution: Annotated[str, Query(description="Distribution name")],
    profile: Annotated[str, Query(description="Profile name")],
    board: Annotated[str, Query(description="Board name")],
) -> dict[str, Any]:
    """Resolve and return a build plan without building."""
    try:
        plan = resolve_plan(distribution, profile, board, db_url=_db(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return plan.to_dict()


@router.post("")
def post_plan(body: PlanRequest, request: Request) -> dict[str, Any]:
    """Resolve a plan with name-based overrides (no build)."""
    try:
        return orchestrator.resolve_plan_request(
            distribution=body.distribution,
            profile=body.profile,
            board=body.board,
            overrides=body.overrides,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/validate")
def post_plan_validate(body: PlanRequest, request: Request) -> dict[str, Any]:
    return orchestrator.validate_plan(
        distribution=body.distribution,
        profile=body.profile,
        board=body.board,
        overrides=body.overrides,
        db_url=_db(request),
    )


@router.post("/diff")
def post_plan_diff(body: PlanDiffRequest, request: Request) -> dict[str, Any]:
    try:
        return orchestrator.diff_plans(
            distribution=body.distribution,
            board=body.board,
            a=body.a,
            b=body.b,
            db_url=_db(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing key: {exc}") from exc
    except ValueError as exc:
        raise _guard(exc) from exc


@prefetch_router.post("")
def post_prefetch(body: PlanRequest, request: Request) -> dict[str, Any]:
    """Report what a plan would need to fetch/build (no build started)."""
    try:
        return orchestrator.prefetch_report(
            distribution=body.distribution,
            profile=body.profile,
            board=body.board,
            overrides=body.overrides,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc
