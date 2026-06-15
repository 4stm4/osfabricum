"""M53 — Hardware probe import API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import probe
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["probe"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


@router.get("/probe-source-kinds")
def list_source_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = probe.list_probe_source_kinds(s)
    return [{"kind": k.kind, "label": k.label, "description": k.description,
              "display_order": k.display_order} for k in kinds]


@router.get("/hardware-probes")
def list_probes(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        probes = probe.list_hardware_probes(s)
    return [_probe_dict(p) for p in probes]


@router.post("/hardware-probes", dependencies=[require_write_auth])
def import_probe(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = probe.import_hardware_probe(
                s,
                name=body["name"],
                probe_data=body.get("probe_data", {}),
                probe_source=body.get("probe_source", "manual"),
                board_id=body.get("board_id"),
            )
            s.commit()
            return _probe_dict(p)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hardware-probes/{probe_id}")
def get_probe(req: Request, probe_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = probe.get_hardware_probe(s, probe_id)
            return _probe_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/hardware-probes/{probe_id}", dependencies=[require_write_auth])
def delete_probe(req: Request, probe_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            probe.delete_hardware_probe(s, probe_id)
            s.commit()
            return {"deleted": probe_id}
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _probe_dict(p: object) -> dict:
    return {
        "id": p.id, "name": p.name, "board_id": p.board_id,
        "probe_source": p.probe_source,
        "cpu_arch": p.cpu_arch, "cpu_model": p.cpu_model, "mem_mb": p.mem_mb,
        "content_hash": p.content_hash,
        "probed_at": p.probed_at.isoformat() if p.probed_at else None,
        "created_at": p.created_at.isoformat(),
    }
