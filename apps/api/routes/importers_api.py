"""M63 — Importers from Competitors API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import importers as imp_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["importers"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/import-kinds")
def list_import_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = imp_svc.list_import_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.post("/imports/{kind}", dependencies=[require_write_auth])
def create_import_job(req: Request, kind: str, body: dict | None = None) -> dict:
    b = body or {}
    with sync_session(_db(req)) as s:
        try:
            job = imp_svc.create_import_job(
                s, import_kind=kind,
                source_data=b.get("source_data"),
                source_filename=b.get("source_filename"),
            )
            s.commit()
            s.refresh(job)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _job_dict(job)


@router.get("/imports")
def list_import_jobs(
    req: Request,
    import_kind: str | None = None,
    status: str | None = None,
) -> list[dict]:
    with sync_session(_db(req)) as s:
        jobs = imp_svc.list_import_jobs(s, import_kind, status)
    return [_job_dict(j) for j in jobs]


@router.get("/imports/{job_id}")
def get_import_job(req: Request, job_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            job = imp_svc.get_import_job(s, job_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _job_dict(job)


@router.post("/imports/{job_id}/run", dependencies=[require_write_auth])
def run_import(req: Request, job_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            report = imp_svc.run_import(s, job_id)
            s.commit()
            s.refresh(report)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(report)


@router.get("/imports/{job_id}/report")
def get_import_report(req: Request, job_id: str) -> dict:
    with sync_session(_db(req)) as s:
        report = imp_svc.get_import_report(s, job_id)
    if report is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No report for this job yet")
    return _report_dict(report)


def _job_dict(j) -> dict:
    return {
        "id": j.id, "import_kind": j.import_kind, "status": j.status,
        "source_filename": j.source_filename,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


def _report_dict(r) -> dict:
    return {
        "id": r.id, "import_job_id": r.import_job_id,
        "mapped_count": r.mapped_count, "unknown_count": r.unknown_count,
        "report_text": r.report_text,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
