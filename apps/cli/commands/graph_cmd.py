"""M57 — Dependency Graph CLI commands."""

from __future__ import annotations

import typer

from osfabricum import graph as graph_svc
from osfabricum.db.session import sync_session
from osfabricum.settings import load_settings

graph_app = typer.Typer(help="Dependency graph viewer")


def _db() -> str:
    return load_settings().database.url


@graph_app.command("kinds")
def list_kinds() -> None:
    """List available graph kinds."""
    with sync_session(_db()) as s:
        kinds = graph_svc.list_graph_kinds(s)
    for k in kinds:
        typer.echo(f"{k.kind:20s} {k.label}")


@graph_app.command("compute")
def compute(
    kind: str = typer.Argument(..., help="Graph kind (e.g. package, layer)"),
    root_node: str | None = typer.Option(None, "--root", "-r", help="Root node filter"),
    distribution_id: str | None = typer.Option(None, "--dist", help="Distribution ID"),
) -> None:
    """Compute a graph snapshot."""
    with sync_session(_db()) as s:
        snap = graph_svc.compute_graph(s, kind, distribution_id, root_node)
        s.commit()
    typer.echo(f"Snapshot {snap.id}: {snap.node_count} nodes, {snap.edge_count} edges")
    typer.echo(f"Hash: {snap.content_hash}")


@graph_app.command("reverse")
def reverse(
    kind: str = typer.Argument(..., help="Graph kind"),
    node: str = typer.Argument(..., help="Node to find reverse deps for"),
) -> None:
    """Compute reverse dependency graph (who depends on <node>)."""
    with sync_session(_db()) as s:
        snap = graph_svc.compute_reverse_graph(s, kind, node)
        s.commit()
    typer.echo(f"Reverse snapshot {snap.id}: {snap.node_count} nodes, {snap.edge_count} edges")


@graph_app.command("snapshots")
def list_snapshots(
    kind: str | None = typer.Option(None, "--kind", "-k"),
) -> None:
    """List graph snapshots."""
    with sync_session(_db()) as s:
        snaps = graph_svc.list_graph_snapshots(s, kind)
    for sn in snaps:
        typer.echo(
            f"{sn.id}  {sn.kind:12s}  nodes={sn.node_count}  "
            f"edges={sn.edge_count}  {sn.created_at}"
        )
