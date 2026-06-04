"""``osfabricumctl source`` subcommands (M7)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Artifact, Source
from osfabricum.db.session import sync_session

source_app = typer.Typer(help="Manage build sources", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)

_DEFAULT_STORE = Path("~/.osfabricum/store").expanduser()


def _display_name(src: Source) -> str:
    meta = src.metadata_json or {}
    return str(meta.get("name") or src.uri.rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------
# source list
# ---------------------------------------------------------------------------


@source_app.command("list")
def source_list(
    db_url: Annotated[str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")] = None,
) -> None:
    """List registered sources."""
    try:
        with sync_session(db_url) as session:
            rows = session.scalars(select(Source).order_by(Source.uri)).all()
            fetched_keys = {
                art.store_key.split("/")[1]  # store_key = "source/<id>/..."
                for art in session.scalars(select(Artifact).where(Artifact.kind == "source")).all()
            }
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    tbl = Table("Name", "Type", "Ref", "Cached", "URI", title="Sources")
    for r in rows:
        cached = "yes" if r.id in fetched_keys else "no"
        tbl.add_row(
            _display_name(r),
            r.source_type,
            r.ref or "",
            cached,
            r.uri,
        )
    Console().print(tbl)


# ---------------------------------------------------------------------------
# source show
# ---------------------------------------------------------------------------


@source_app.command("show")
def source_show(
    identifier: Annotated[str, typer.Argument(help="URI, id, or name")],
    db_url: Annotated[str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")] = None,
) -> None:
    """Show details for a single source."""
    try:
        from osfabricum.fetcher.fetch import _lookup_source

        src = _lookup_source(identifier, db_url)
        with sync_session(db_url) as session:
            artifact = session.scalar(
                select(Artifact).where(Artifact.store_key.like(f"source/{src.id}/%"))
            )
    except ValueError:
        typer.secho(f"source not found: {identifier!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    c = Console()
    c.print(f"[bold]Name[/bold]:          {_display_name(src)}")
    c.print(f"[bold]ID[/bold]:            {src.id}")
    c.print(f"[bold]URI[/bold]:           {src.uri}")
    c.print(f"[bold]Type[/bold]:          {src.source_type}")
    if src.ref:
        c.print(f"[bold]Ref[/bold]:           {src.ref}")
    if src.expected_hash:
        c.print(f"[bold]Expected hash[/bold]: {src.expected_hash}")
    meta = src.metadata_json or {}
    if meta.get("tarball_url"):
        c.print(f"[bold]Tarball URL[/bold]:   {meta['tarball_url']}")
    if artifact is not None:
        c.print(f"[bold]Artifact ID[/bold]:   {artifact.id}")
        c.print(f"[bold]SHA-256[/bold]:       {artifact.blob_sha256}")
        size_kb = (artifact.size_bytes or 0) // 1024
        c.print(f"[bold]Size[/bold]:          {size_kb} KiB")
    else:
        c.print("[bold]Cached[/bold]:        no")


# ---------------------------------------------------------------------------
# source add
# ---------------------------------------------------------------------------


@source_app.command("add")
def source_add(
    uri: Annotated[str, typer.Argument(help="Source URI (HTTP URL or git repo URL)")],
    source_type: Annotated[
        str, typer.Option("--type", help="Source type: http | https | git")
    ] = "http",
    ref: Annotated[
        str | None, typer.Option("--ref", help="Branch / tag / commit for git sources")
    ] = None,
    expected_hash: Annotated[
        str | None,
        typer.Option("--hash", help="Expected sha256 (hex or sha256:<hex>)"),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Human-readable name alias")] = None,
    tarball_url: Annotated[
        str | None,
        typer.Option("--tarball-url", help="Pre-built tarball URL (git fast path)"),
    ] = None,
    db_url: Annotated[str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")] = None,
) -> None:
    """Register a source in the catalog (without fetching)."""
    try:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Source).where(Source.uri == uri))
            if existing is not None:
                typer.echo(f"Source already registered (id={existing.id})")
                return
            meta: dict[str, object] = {}
            if name:
                meta["name"] = name
            if tarball_url:
                meta["tarball_url"] = tarball_url
            session.add(
                Source(
                    uri=uri,
                    source_type=source_type,
                    ref=ref,
                    expected_hash=expected_hash,
                    metadata_json=meta or None,
                )
            )
            session.commit()
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    typer.echo(f"Registered source {uri!r}")


# ---------------------------------------------------------------------------
# source fetch
# ---------------------------------------------------------------------------


@source_app.command("fetch")
def source_fetch(
    identifier: Annotated[str, typer.Argument(help="URI, id, or name")],
    store: Annotated[
        Path,
        typer.Option("--store", help="Artifact store root directory"),
    ] = _DEFAULT_STORE,
    offline: Annotated[
        bool, typer.Option("--offline/--no-offline", help="Serve from cache only")
    ] = False,
    db_url: Annotated[str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")] = None,
) -> None:
    """Download and store a source."""
    from osfabricum.fetcher.fetch import fetch_source

    mode = " (offline)" if offline else ""
    typer.echo(f"Fetching source {identifier!r}{mode} …")
    try:
        artifact_id = fetch_source(identifier, store, db_url, offline=offline)
    except (ValueError, RuntimeError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    typer.echo(f"Stored as artifact {artifact_id}")
