"""M63 — Importers CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from osfabricum import importers as imp_svc
from osfabricum.db.session import sync_session

importers_app = typer.Typer(help="Import foreign OS configs into OSFabricum", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@importers_app.command("run")
def run_import(
    import_kind: Annotated[str, typer.Argument(help="buildroot|openwrt|yocto|debian|alpine|nixos|rootfs|image|kconfig")],
    source_file: Annotated[Path, typer.Argument(help="Path to source config file")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Run an import job from a source config file."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    source_data = source_file.read_text()
    with sync_session(url) as s:
        try:
            job = imp_svc.create_import_job(
                s, import_kind=import_kind,
                source_data=source_data,
                source_filename=str(source_file),
            )
            s.commit()
            s.refresh(job)
            report = imp_svc.run_import(s, job.id)
            s.commit()
            s.refresh(report)
        except (KeyError, ValueError) as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"import-job: {job.id}  kind={import_kind}  status={job.status}")
    typer.echo(f"mapped={report.mapped_count}  unknown={report.unknown_count}")
    if report.report_text:
        typer.echo(report.report_text)


@importers_app.command("list")
def list_jobs(
    import_kind: Annotated[str | None, typer.Option("--kind")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List import jobs."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        jobs = imp_svc.list_import_jobs(s, import_kind=import_kind)
    if not jobs:
        typer.echo("(no import jobs)")
        return
    for j in jobs:
        typer.echo(f"{j.id[:8]}  kind={j.import_kind}  status={j.status}")


@importers_app.command("show")
def show_job(
    job_id: Annotated[str, typer.Argument(help="Import job ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Show import job report."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            job = imp_svc.get_import_job(s, job_id)
            report = imp_svc.get_import_report(s, job_id)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"id:     {job.id}")
    typer.echo(f"kind:   {job.import_kind}")
    typer.echo(f"status: {job.status}")
    if report:
        typer.echo(f"mapped:  {report.mapped_count}  unknown: {report.unknown_count}")
        typer.echo(report.report_text or "")
