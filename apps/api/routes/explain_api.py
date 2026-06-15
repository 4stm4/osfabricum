"""M58 — Explain / Why Engine API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import explain as explain_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["explain"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/explain-trace-kinds")
def list_explain_trace_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = explain_svc.list_explain_trace_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.post("/explain/traces", dependencies=[require_write_auth])
def add_trace(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            t = explain_svc.add_trace(
                s,
                target_kind=body["target_kind"],
                target_key=body["target_key"],
                reason_kind=body["reason_kind"],
                reason_detail=body.get("reason_detail", ""),
                build_id=body.get("build_id"),
                source_id=body.get("source_id"),
            )
            s.commit()
            s.refresh(t)
        except (KeyError, ValueError) as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _trace_dict(t)


@router.get("/explain/traces")
def list_traces(
    req: Request,
    build_id: str | None = None,
    target_kind: str | None = None,
    reason_kind: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        traces = explain_svc.list_traces(s, build_id, target_kind, reason_kind)
    return [_trace_dict(t) for t in traces]


@router.get("/explain/item")
def explain_item(
    req: Request,
    target_key: str,
    target_kind: str | None = None,
    build_id: str | None = None,
) -> dict:
    with sync_session(_db(req)) as s:
        traces = explain_svc.explain_item(s, target_key, target_kind, build_id)
        text = explain_svc.render_explain_text(traces)
    return {"target_key": target_key, "trace_count": len(traces), "rendered": text,
            "traces": [_trace_dict(t) for t in traces]}


@router.get("/builds/{build_id}/explain")
def explain_build(req: Request, build_id: str) -> dict:
    with sync_session(_db(req)) as s:
        traces = explain_svc.explain_build(s, build_id)
        text = explain_svc.render_explain_text(traces)
    return {"build_id": build_id, "trace_count": len(traces), "rendered": text,
            "traces": [_trace_dict(t) for t in traces]}


def _trace_dict(t) -> dict:
    return {
        "id": t.id,
        "build_id": t.build_id,
        "target_kind": t.target_kind,
        "target_key": t.target_key,
        "reason_kind": t.reason_kind,
        "reason_detail": t.reason_detail,
        "source_id": t.source_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
