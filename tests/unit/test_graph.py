"""Unit tests for M57 — Dependency Graph Viewer."""

from __future__ import annotations

import json

import pytest

from osfabricum import graph as graph_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_graph_kinds


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_graph.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_graph_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Graph kinds
# ---------------------------------------------------------------------------


def test_graph_kinds_seeded(session):
    kinds = graph_svc.list_graph_kinds(session)
    assert len(kinds) == 7


def test_graph_kinds_ordered(session):
    kinds = graph_svc.list_graph_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_graph_kinds_have_label(session):
    kinds = graph_svc.list_graph_kinds(session)
    assert all(k.label for k in kinds)


def test_graph_kinds_valid_set(session):
    kinds = graph_svc.list_graph_kinds(session)
    names = {k.kind for k in kinds}
    assert names == graph_svc.VALID_GRAPH_KINDS


# ---------------------------------------------------------------------------
# Compute graph — stub kinds
# ---------------------------------------------------------------------------


def test_compute_graph_unknown_kind_raises(session):
    with pytest.raises(ValueError, match="Invalid graph kind"):
        graph_svc.compute_graph(session, "bogus-kind")


def test_compute_stub_graph_returns_snapshot(session):
    snap = graph_svc.compute_graph(session, "build")
    assert snap.id is not None
    assert snap.kind == "build"


def test_compute_stub_graph_has_json(session):
    snap = graph_svc.compute_graph(session, "runtime")
    data = json.loads(snap.rendered_graph_json)
    assert "kind" in data
    assert "nodes" in data
    assert "edges" in data


def test_compute_stub_graph_nodes_edges_count(session):
    snap = graph_svc.compute_graph(session, "kernel")
    assert snap.node_count == len(json.loads(snap.rendered_graph_json)["nodes"])
    assert snap.edge_count == len(json.loads(snap.rendered_graph_json)["edges"])


def test_compute_stub_has_hash(session):
    snap = graph_svc.compute_graph(session, "service")
    assert snap.content_hash is not None
    assert snap.content_hash.startswith("sha256:")


def test_compute_stub_has_rendered_at(session):
    snap = graph_svc.compute_graph(session, "image")
    assert snap.rendered_at is not None


# ---------------------------------------------------------------------------
# Compute graph — package kind (empty DB)
# ---------------------------------------------------------------------------


def test_compute_package_graph_empty(session):
    snap = graph_svc.compute_graph(session, "package")
    assert snap.kind == "package"
    data = json.loads(snap.rendered_graph_json)
    assert data["kind"] == "package"
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


def test_compute_package_graph_with_root(session):
    snap = graph_svc.compute_graph(session, "package", root_node="glibc")
    data = json.loads(snap.rendered_graph_json)
    assert "nodes" in data


# ---------------------------------------------------------------------------
# Compute graph — layer kind (empty DB)
# ---------------------------------------------------------------------------


def test_compute_layer_graph_empty(session):
    snap = graph_svc.compute_graph(session, "layer")
    data = json.loads(snap.rendered_graph_json)
    assert data["kind"] == "layer"
    assert data["nodes"] == []


# ---------------------------------------------------------------------------
# Reverse graph
# ---------------------------------------------------------------------------


def test_compute_reverse_unknown_kind_raises(session):
    with pytest.raises(ValueError, match="Invalid graph kind"):
        graph_svc.compute_reverse_graph(session, "invalid", "glibc")


def test_compute_reverse_package_empty(session):
    snap = graph_svc.compute_reverse_graph(session, "package", "glibc")
    data = json.loads(snap.rendered_graph_json)
    assert data["mode"] == "reverse"
    assert any(n["id"] == "glibc" for n in data["nodes"])


def test_compute_reverse_stub_kind(session):
    snap = graph_svc.compute_reverse_graph(session, "build", "my-build")
    data = json.loads(snap.rendered_graph_json)
    assert data["mode"] == "reverse"
    assert len(data["nodes"]) == 1


def test_compute_reverse_sets_root_node(session):
    snap = graph_svc.compute_reverse_graph(session, "package", "busybox")
    assert "reverse:" in snap.root_node


def test_compute_reverse_has_hash(session):
    snap = graph_svc.compute_reverse_graph(session, "package", "glibc")
    assert snap.content_hash is not None
    assert snap.content_hash.startswith("sha256:")


# ---------------------------------------------------------------------------
# Snapshots CRUD
# ---------------------------------------------------------------------------


def test_list_snapshots_empty(session):
    assert graph_svc.list_graph_snapshots(session) == []


def test_list_snapshots_after_compute(session):
    graph_svc.compute_graph(session, "build")
    graph_svc.compute_graph(session, "runtime")
    snaps = graph_svc.list_graph_snapshots(session)
    assert len(snaps) == 2


def test_list_snapshots_filter_by_kind(session):
    graph_svc.compute_graph(session, "build")
    graph_svc.compute_graph(session, "kernel")
    snaps = graph_svc.list_graph_snapshots(session, kind="build")
    assert len(snaps) == 1
    assert snaps[0].kind == "build"


def test_get_snapshot_found(session):
    snap = graph_svc.compute_graph(session, "service")
    fetched = graph_svc.get_graph_snapshot(session, snap.id)
    assert fetched.id == snap.id


def test_get_snapshot_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        graph_svc.get_graph_snapshot(session, "nonexistent-uuid")


def test_snapshot_ordered_desc_by_created_at(session):
    s1 = graph_svc.compute_graph(session, "build")
    s2 = graph_svc.compute_graph(session, "runtime")
    snaps = graph_svc.list_graph_snapshots(session)
    ids = [s.id for s in snaps]
    assert ids[0] == s2.id
    assert ids[1] == s1.id


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_hash_same_inputs_same_hash(session):
    s1 = graph_svc.compute_graph(session, "build")
    s2 = graph_svc.compute_graph(session, "build")
    assert s1.content_hash == s2.content_hash


def test_different_kinds_different_hashes(session):
    s1 = graph_svc.compute_graph(session, "build")
    s2 = graph_svc.compute_graph(session, "runtime")
    assert s1.content_hash != s2.content_hash
