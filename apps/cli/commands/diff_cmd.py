"""M59 — Build / Profile / Release Diff CLI commands."""

from __future__ import annotations

import typer

from osfabricum import diff as diff_svc
from osfabricum.db.session import sync_session
from osfabricum.settings import load_settings

diff_app = typer.Typer(help="Build / profile / release diff")


def _db() -> str:
    return load_settings().database.url


@diff_app.command("kinds")
def list_kinds() -> None:
    """List diff report kinds."""
    with sync_session(_db()) as s:
        kinds = diff_svc.list_diff_report_kinds(s)
    for k in kinds:
        typer.echo(f"{k.kind:20s} {k.label}")


@diff_app.command("create")
def create_report(
    entity_kind: str = typer.Option(..., "--entity-kind", help="profile|build|release"),
    entity_a: str = typer.Option(..., "--a", help="Entity A ID"),
    entity_b: str = typer.Option(..., "--b", help="Entity B ID"),
    diff_kind: str = typer.Option("package", "--diff-kind"),
) -> None:
    """Create a diff report (placeholder, no data rendered yet)."""
    with sync_session(_db()) as s:
        r = diff_svc.create_diff_report(s, entity_kind, entity_a, entity_b, diff_kind)
        s.commit()
    typer.echo(f"DiffReport {r.id} created: {entity_kind} {entity_a} → {entity_b}")


@diff_app.command("list")
def list_reports(
    entity_kind: str | None = typer.Option(None, "--entity-kind"),
) -> None:
    """List diff reports."""
    with sync_session(_db()) as s:
        reports = diff_svc.list_diff_reports(s, entity_kind)
    for r in reports:
        typer.echo(
            f"{r.id}  {r.entity_kind:10s}  {r.entity_a_id[:8]}…→{r.entity_b_id[:8]}…  "
            f"hash={r.content_hash or 'pending'}"
        )


@diff_app.command("render")
def render_report(
    report_id: str = typer.Argument(...),
) -> None:
    """Render a diff report (empty data — shows structure)."""
    with sync_session(_db()) as s:
        r = diff_svc.render_diff_report(s, report_id)
        s.commit()
    typer.echo(r.rendered_diff)
