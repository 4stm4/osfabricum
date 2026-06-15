"""Business logic for M57 — Dependency Graph Viewer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from osfabricum.db.models import (
    GraphKind,
    GraphSnapshot,
    LayerEntry,
    Package,
    PackageDependency,
    PackageVersion,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_GRAPH_KINDS: frozenset[str] = frozenset(
    {"package", "build", "runtime", "kernel", "service", "image", "layer"}
)


def list_graph_kinds(session: "Session") -> list[GraphKind]:
    return list(
        session.scalars(select(GraphKind).order_by(GraphKind.display_order)).all()
    )


def list_graph_snapshots(
    session: "Session", kind: str | None = None
) -> list[GraphSnapshot]:
    q = select(GraphSnapshot).order_by(GraphSnapshot.created_at.desc())
    if kind is not None:
        q = q.where(GraphSnapshot.kind == kind)
    return list(session.scalars(q).all())


def get_graph_snapshot(session: "Session", snapshot_id: str) -> GraphSnapshot:
    s = session.get(GraphSnapshot, snapshot_id)
    if s is None:
        raise KeyError(f"Graph snapshot {snapshot_id!r} not found")
    return s


def compute_graph(
    session: "Session",
    kind: str,
    distribution_id: str | None = None,
    root_node: str | None = None,
) -> GraphSnapshot:
    if kind not in VALID_GRAPH_KINDS:
        raise ValueError(
            f"Invalid graph kind {kind!r}. Valid: {sorted(VALID_GRAPH_KINDS)}"
        )
    if kind == "package":
        graph = _compute_package_graph(session, root_node)
    elif kind == "layer":
        graph = _compute_layer_graph(session, distribution_id)
    else:
        graph = _compute_stub_graph(kind, root_node)

    graph_json = json.dumps(graph, sort_keys=True)
    content_hash = "sha256:" + hashlib.sha256(graph_json.encode()).hexdigest()

    snap = GraphSnapshot(
        id=_uuid(), kind=kind, distribution_id=distribution_id,
        root_node=root_node,
        rendered_graph_json=graph_json,
        node_count=len(graph["nodes"]),
        edge_count=len(graph["edges"]),
        content_hash=content_hash,
        rendered_at=datetime.utcnow(),
        created_at=_now(),
    )
    session.add(snap)
    session.flush()
    return snap


def compute_reverse_graph(
    session: "Session",
    kind: str,
    node: str,
    distribution_id: str | None = None,
) -> GraphSnapshot:
    """Compute 'who depends on <node>'."""
    if kind not in VALID_GRAPH_KINDS:
        raise ValueError(
            f"Invalid graph kind {kind!r}. Valid: {sorted(VALID_GRAPH_KINDS)}"
        )
    if kind == "package":
        graph = _compute_package_reverse(session, node)
    else:
        graph = {"nodes": [{"id": node, "label": node}], "edges": [],
                 "kind": kind, "mode": "reverse"}

    graph_json = json.dumps(graph, sort_keys=True)
    content_hash = "sha256:" + hashlib.sha256(graph_json.encode()).hexdigest()

    snap = GraphSnapshot(
        id=_uuid(), kind=kind, distribution_id=distribution_id,
        root_node=f"reverse:{node}",
        rendered_graph_json=graph_json,
        node_count=len(graph["nodes"]),
        edge_count=len(graph["edges"]),
        content_hash=content_hash,
        rendered_at=datetime.utcnow(),
        created_at=_now(),
    )
    session.add(snap)
    session.flush()
    return snap


def _compute_package_graph(
    session: "Session", root_node: str | None
) -> dict[str, Any]:
    deps = session.scalars(select(PackageDependency)).all()
    pkgs = {p.name for p in session.scalars(select(Package)).all()}

    nodes_set: set[str] = set(pkgs)
    edges: list[dict] = []

    for dep in deps:
        version = session.get(PackageVersion, dep.src_version_id)
        if version is None:
            continue
        pkg = session.get(Package, version.package_id)
        if pkg is None:
            continue
        src = pkg.name
        dst = dep.dep_name
        nodes_set.add(src)
        nodes_set.add(dst)
        if root_node is None or src == root_node or dst == root_node:
            edges.append({"from": src, "to": dst, "type": dep.dep_type})

    if root_node is not None:
        reachable = {root_node}
        for e in edges:
            reachable.add(e["from"])
            reachable.add(e["to"])
        nodes_list = [{"id": n, "label": n} for n in sorted(reachable)]
    else:
        nodes_list = [{"id": n, "label": n} for n in sorted(nodes_set)]

    return {"kind": "package", "nodes": nodes_list, "edges": edges}


def _compute_package_reverse(session: "Session", node: str) -> dict[str, Any]:
    deps = session.scalars(
        select(PackageDependency).where(PackageDependency.dep_name == node)
    ).all()

    nodes_set: set[str] = {node}
    edges: list[dict] = []
    for dep in deps:
        version = session.get(PackageVersion, dep.src_version_id)
        if version is None:
            continue
        pkg = session.get(Package, version.package_id)
        if pkg is None:
            continue
        src = pkg.name
        nodes_set.add(src)
        edges.append({"from": src, "to": node, "type": dep.dep_type})

    return {
        "kind": "package", "mode": "reverse",
        "nodes": [{"id": n, "label": n} for n in sorted(nodes_set)],
        "edges": edges,
    }


def _compute_layer_graph(
    session: "Session", distribution_id: str | None
) -> dict[str, Any]:
    q = select(LayerEntry).order_by(LayerEntry.priority, LayerEntry.name)
    entries = session.scalars(q).all()

    nodes: list[dict] = []
    edges: list[dict] = []
    prev: str | None = None
    for e in entries:
        if not e.is_enabled:
            continue
        node_id = f"{e.layer_kind}:{e.name}"
        nodes.append({"id": node_id, "label": e.name, "kind": e.layer_kind,
                      "priority": e.priority})
        if prev is not None:
            edges.append({"from": prev, "to": node_id, "type": "priority-order"})
        prev = node_id

    return {"kind": "layer", "nodes": nodes, "edges": edges}


def _compute_stub_graph(kind: str, root_node: str | None) -> dict[str, Any]:
    return {
        "kind": kind, "nodes": [], "edges": [],
        "note": f"{kind} graph computation requires {kind}-specific data collection.",
    }
