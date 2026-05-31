"""Real implementations of ``osfabricumctl artifacts`` subcommands (M3)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session

artifacts_app = typer.Typer(help="Browse the artifact store", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


@artifacts_app.command("list")
def artifacts_list(
    kind: Annotated[str | None, typer.Option("--kind", help="Filter by artifact kind")] = None,
    arch: Annotated[str | None, typer.Option("--arch", help="Filter by arch")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Filter by name")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """List artifacts recorded in the store."""
    try:
        with sync_session(db_url) as session:
            query = select(Artifact).order_by(Artifact.created_at.desc())
            if kind is not None:
                query = query.where(Artifact.kind == kind)
            if arch is not None:
                query = query.where(Artifact.arch == arch)
            if name is not None:
                query = query.where(Artifact.name == name)
            rows = session.scalars(query).all()
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    tbl = Table("Name", "Kind", "Version", "Arch", "SHA256", "Bytes", title="Artifacts")
    for r in rows:
        size = f"{r.size_bytes:,}" if r.size_bytes is not None else ""
        tbl.add_row(
            r.name,
            r.kind,
            r.version or "",
            r.arch or "",
            r.blob_sha256[:16] + "...",
            size,
        )
    Console().print(tbl)


@artifacts_app.command("show")
def artifacts_show(
    name: Annotated[str, typer.Argument(help="Artifact name or store_key")],
) -> None:
    """Show details for a single artifact."""
    typer.secho("`artifacts show` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@artifacts_app.command("download")
def artifacts_download(
    name: Annotated[str, typer.Argument(help="Artifact name or store_key")],
) -> None:
    """Download an artifact from the store."""
    typer.secho("`artifacts download` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@artifacts_app.command("verify")
def artifacts_verify(
    name: Annotated[str, typer.Argument(help="Artifact name or store_key")],
) -> None:
    """Verify a single artifact's sha256."""
    typer.secho("`artifacts verify` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@artifacts_app.command("pin")
def artifacts_pin(
    name: Annotated[str, typer.Argument(help="Artifact name or store_key")],
) -> None:
    """Pin an artifact to prevent GC."""
    typer.secho("`artifacts pin` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@artifacts_app.command("unpin")
def artifacts_unpin(
    name: Annotated[str, typer.Argument(help="Artifact name or store_key")],
) -> None:
    """Unpin an artifact."""
    typer.secho("`artifacts unpin` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
