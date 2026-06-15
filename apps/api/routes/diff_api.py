"""M59 — Build / Profile / Release Diff API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import diff as diff_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["diff"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/diff-report-kinds")
def list_diff_report_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = diff_svc.list_diff_report_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.get("/diff-reports")
def list_diff_reports(
    req: Request,
    entity_kind: str | None = None,
    entity_a_id: str | None = None,
    entity_b_id: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        reports = diff_svc.list_diff_reports(s, entity_kind, entity_a_id, entity_b_id)
    return [_report_dict(r) for r in reports]


@router.post("/diff-reports", dependencies=[require_write_auth])
def create_diff_report(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = diff_svc.create_diff_report(
                s,
                entity_kind=body["entity_kind"],
                entity_a_id=body["entity_a_id"],
                entity_b_id=body["entity_b_id"],
                diff_kind=body.get("diff_kind", "package"),
            )
            s.commit()
            s.refresh(r)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _report_dict(r)


@router.get("/diff-reports/{report_id}")
def get_diff_report(req: Request, report_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            r = diff_svc.get_diff_report(s, report_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(r, include_rendered=True)


@router.post("/diff-reports/{report_id}/render", dependencies=[require_write_auth])
def render_diff_report(req: Request, report_id: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        try:
            r = diff_svc.render_diff_report(
                s, report_id,
                a_data=b.get("a_data"),
                b_data=b.get("b_data"),
            )
            s.commit()
            s.refresh(r)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(r, include_rendered=True)


def _report_dict(r, include_rendered: bool = False) -> dict:
    d: dict = {
        "id": r.id,
        "entity_kind": r.entity_kind,
        "entity_a_id": r.entity_a_id,
        "entity_b_id": r.entity_b_id,
        "content_hash": r.content_hash,
        "summary_json": r.summary_json,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if include_rendered:
        d["rendered_diff"] = r.rendered_diff
    return d
