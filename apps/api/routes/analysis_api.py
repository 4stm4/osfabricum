"""M64 — Build Analysis Dashboard API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import analysis as analysis_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["analysis"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/builds/{build_id}/analysis")
def get_build_analyses(
    req: Request, build_id: str, kind: str | None = None
) -> list[dict]:
    with sync_session(_db(req)) as s:
        analyses = analysis_svc.list_build_analyses(s, build_id, kind)
    return [_analysis_dict(a) for a in analyses]


@router.post("/builds/{build_id}/analysis", dependencies=[require_write_auth])
def run_analysis(req: Request, build_id: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        try:
            a = analysis_svc.analyze_build(
                s, build_id=build_id,
                analysis_kind=b.get("analysis_kind", "time"),
                input_data=b.get("input_data"),
            )
            s.commit()
            s.refresh(a)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _analysis_dict(a, include_report=True)


@router.get("/analyses/{analysis_id}")
def get_analysis(req: Request, analysis_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            a = analysis_svc.get_build_analysis(s, analysis_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _analysis_dict(a, include_report=True)


def _analysis_dict(a, include_report: bool = False) -> dict:
    d: dict = {
        "id": a.id, "build_id": a.build_id, "analysis_kind": a.analysis_kind,
        "content_hash": a.content_hash, "summary_json": a.summary_json,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if include_report:
        d["rendered_report"] = a.rendered_report
    return d
