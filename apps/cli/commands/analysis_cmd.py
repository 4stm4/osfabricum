"""M64 — Build Analysis CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import analysis as an_svc
from osfabricum.db.session import sync_session

analysis_app = typer.Typer(help="Build analysis reports (time, size, cache, warnings)", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@analysis_app.command("run")
def run_analysis(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    kind: Annotated[str, typer.Option("--kind", help="time|size|critical-path|cache|warnings")] = "time",
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Analyze a build."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            report = an_svc.analyze_build(s, build_id=build_id, analysis_kind=kind)
            s.commit()
            s.refresh(report)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"analysis: {report.id}  kind={report.analysis_kind}  hash={report.content_hash or '—'}")
    if report.rendered_report:
        typer.echo(report.rendered_report)


@analysis_app.command("list")
def list_analyses(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List analyses for a build."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        analyses = an_svc.list_build_analyses(s, build_id=build_id)
    if not analyses:
        typer.echo("(no analyses)")
        return
    for a in analyses:
        typer.echo(f"{a.id[:8]}  kind={a.analysis_kind}  hash={a.content_hash or '—'}")


@analysis_app.command("show")
def show_analysis(
    analysis_id: Annotated[str, typer.Argument(help="Analysis ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Show analysis report."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            a = an_svc.get_build_analysis(s, analysis_id)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"id:   {a.id}")
    typer.echo(f"kind: {a.analysis_kind}")
    typer.echo(f"hash: {a.content_hash or '—'}")
    typer.echo(a.rendered_report or "(no report)")
