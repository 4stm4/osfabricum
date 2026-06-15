"""M57 — Dependency Graph Viewer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import graph as graph_svc
from osfabricum.db.session import sync_session
from osfabricum.security.auth_policy import require_write_auth

router = APIRouter(prefix="/v1", tags=["graph"])


def _db(req: Request) -> str:
    return req.app.state.settings.database.url


@router.get("/graph-kinds")
def list_graph_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = graph_svc.list_graph_kinds(s)
    return [
        {"kind": k.kind, "label": k.label, "description": k.description,
         "display_order": k.display_order}
        for k in kinds
    ]


@router.get("/graph-snapshots")
def list_graph_snapshots(req: Request, kind: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        snaps = graph_svc.list_graph_snapshots(s, kind)
    return [_snap_dict(sn) for sn in snaps]


@router.get("/graph-snapshots/{snapshot_id}")
def get_graph_snapshot(req: Request, snapshot_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            sn = graph_svc.get_graph_snapshot(s, snapshot_id)
        except KeyError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=str(exc))
    return _snap_dict(sn, include_json=True)


@router.post("/graphs/{kind}/compute", dependencies=[require_write_auth])
def compute_graph(
    req: Request,
    kind: str,
    distribution_id: str | None = None,
    root_node: str | None = None,
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            sn = graph_svc.compute_graph(s, kind, distribution_id, root_node)
            s.commit()
            s.refresh(sn)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _snap_dict(sn, include_json=True)


@router.post("/graphs/{kind}/reverse", dependencies=[require_write_auth])
def compute_reverse_graph(
    req: Request,
    kind: str,
    node: str,
    distribution_id: str | None = None,
) -> dict:
    with sync_session(_db(req)) as s:
        try:
            sn = graph_svc.compute_reverse_graph(s, kind, node, distribution_id)
            s.commit()
            s.refresh(sn)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc))
    return _snap_dict(sn, include_json=True)


def _snap_dict(sn, include_json: bool = False) -> dict:
    d: dict = {
        "id": sn.id,
        "kind": sn.kind,
        "distribution_id": sn.distribution_id,
        "root_node": sn.root_node,
        "node_count": sn.node_count,
        "edge_count": sn.edge_count,
        "content_hash": sn.content_hash,
        "rendered_at": sn.rendered_at.isoformat() if sn.rendered_at else None,
        "created_at": sn.created_at.isoformat() if sn.created_at else None,
    }
    if include_json:
        d["rendered_graph_json"] = sn.rendered_graph_json
    return d
