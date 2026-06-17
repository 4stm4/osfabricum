"""M65 — Size / Footprint Optimizer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import sizeopt as size_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["sizeopt"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/size-budget-kinds")
def list_budget_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = size_svc.list_size_budget_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.get("/profiles/{profile_id}/size-budget")
def get_size_budget(req: Request, profile_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        budgets = size_svc.list_size_budgets(s, profile_id)
    return [_budget_dict(b) for b in budgets]


@router.post("/profiles/{profile_id}/size-budget", dependencies=[require_write_auth])
def set_size_budget(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            b = size_svc.set_size_budget(
                s, profile_id=profile_id,
                budget_kind=body["budget_kind"],
                budget_bytes=body["budget_bytes"],
                is_hard_limit=body.get("is_hard_limit", False),
            )
            s.commit()
            s.refresh(b)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _budget_dict(b)


@router.get("/builds/{build_id}/size")
def get_size_reports(req: Request, build_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        reports = size_svc.list_size_reports(s, build_id=build_id)
    return [_report_dict(r) for r in reports]


@router.post("/builds/{build_id}/size", dependencies=[require_write_auth])
def analyze_size(req: Request, build_id: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        r = size_svc.analyze_size(
            s, build_id=build_id,
            profile_id=b.get("profile_id"),
            size_data=b.get("size_data"),
        )
        s.commit()
        s.refresh(r)
    return _report_dict(r, include_rendered=True)


def _budget_dict(b) -> dict:
    return {
        "id": b.id, "profile_id": b.profile_id, "budget_kind": b.budget_kind,
        "budget_bytes": b.budget_bytes, "is_hard_limit": b.is_hard_limit,
    }


def _report_dict(r, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": r.id, "build_id": r.build_id, "profile_id": r.profile_id,
        "content_hash": r.content_hash, "summary_json": r.summary_json,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if include_rendered:
        d["rendered_report"] = r.rendered_report
    return d
