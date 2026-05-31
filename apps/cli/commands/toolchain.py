"""``osfabricumctl toolchain`` subcommands (M6)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Architecture, Toolchain, ToolchainArtifact
from osfabricum.db.session import sync_session

toolchain_app = typer.Typer(help="Manage cross-compilation toolchains", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)

_DEFAULT_STORE = Path("~/.osfabricum/store").expanduser()


# ---------------------------------------------------------------------------
# toolchain list
# ---------------------------------------------------------------------------


@toolchain_app.command("list")
def toolchain_list(
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """List registered toolchains."""
    try:
        with sync_session(db_url) as session:
            rows = session.scalars(select(Toolchain).order_by(Toolchain.name)).all()
            arch_map = {a.id: a.name for a in session.scalars(select(Architecture)).all()}
            fetched_ids = {
                ta.toolchain_id
                for ta in session.scalars(select(ToolchainArtifact)).all()
            }
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    tbl = Table("Name", "Arch", "libc", "Version", "Source", "Fetched", title="Toolchains")
    for r in rows:
        tbl.add_row(
            r.name,
            arch_map.get(r.arch_id, r.arch_id),
            r.libc,
            r.version,
            r.source_type,
            "yes" if r.id in fetched_ids else "no",
        )
    Console().print(tbl)


# ---------------------------------------------------------------------------
# toolchain show
# ---------------------------------------------------------------------------


@toolchain_app.command("show")
def toolchain_show(
    name: Annotated[str, typer.Argument(help="Toolchain name")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Show details for a single toolchain."""
    try:
        with sync_session(db_url) as session:
            tc = session.scalar(select(Toolchain).where(Toolchain.name == name))
            if tc is None:
                typer.secho(f"toolchain not found: {name!r}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            arch_row = session.scalar(
                select(Architecture).where(Architecture.id == tc.arch_id)
            )
            ta = session.scalar(
                select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc.id)
            )
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    console = Console()
    console.print(f"[bold]Name[/bold]:        {tc.name}")
    console.print(f"[bold]Arch[/bold]:        {arch_row.name if arch_row else tc.arch_id}")
    console.print(f"[bold]libc[/bold]:        {tc.libc}")
    console.print(f"[bold]Version[/bold]:     {tc.version}")
    console.print(f"[bold]Source type[/bold]: {tc.source_type}")
    meta = tc.metadata_json or {}
    if meta.get("download_url"):
        console.print(f"[bold]Download URL[/bold]: {meta['download_url']}")
    if ta is not None:
        console.print(f"[bold]Artifact ID[/bold]: {ta.artifact_id}")
        if ta.verified_at:
            console.print(f"[bold]Verified at[/bold]: {ta.verified_at}")
    else:
        console.print("[bold]Fetched[/bold]:     no")


# ---------------------------------------------------------------------------
# toolchain fetch
# ---------------------------------------------------------------------------


@toolchain_app.command("fetch")
def toolchain_fetch(
    name: Annotated[str, typer.Argument(help="Toolchain name")],
    store: Annotated[
        Path,
        typer.Option("--store", help="Artifact store root directory"),
    ] = _DEFAULT_STORE,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Download and store a toolchain tarball."""
    from osfabricum.toolchain.fetch import fetch_toolchain

    typer.echo(f"Fetching toolchain {name!r} …")
    try:
        artifact_id = fetch_toolchain(name, store, db_url)
    except ValueError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    typer.echo(f"Stored as artifact {artifact_id}")


# ---------------------------------------------------------------------------
# toolchain add  (stub — registers a toolchain without fetching)
# ---------------------------------------------------------------------------


@toolchain_app.command("add")
def toolchain_add(
    name: Annotated[str, typer.Argument(help="Toolchain name")],
    arch: Annotated[str, typer.Option("--arch", help="Target architecture")],
    libc: Annotated[str, typer.Option("--libc", help="C library (musl / glibc)")],
    version: Annotated[str, typer.Option("--version", help="Toolchain version string")],
    source_type: Annotated[str, typer.Option("--source-type")] = "bootlin-prebuilt",
    download_url: Annotated[str | None, typer.Option("--download-url")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Register a toolchain in the catalog (without fetching)."""
    try:
        with sync_session(db_url) as session:
            arch_row = session.scalar(
                select(Architecture).where(Architecture.name == arch)
            )
            if arch_row is None:
                typer.secho(
                    f"Architecture '{arch}' not found — run 'catalog import' first.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=1)
            existing = session.scalar(select(Toolchain).where(Toolchain.name == name))
            if existing is not None:
                typer.echo(f"Toolchain {name!r} already registered (id={existing.id})")
                return
            meta: dict[str, object] = {}
            if download_url:
                meta["download_url"] = download_url
            session.add(
                Toolchain(
                    name=name,
                    arch_id=arch_row.id,
                    libc=libc,
                    version=version,
                    source_type=source_type,
                    metadata_json=meta or None,
                )
            )
            session.commit()
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    typer.echo(f"Registered toolchain {name!r}")


# ---------------------------------------------------------------------------
# toolchain verify  (stub)
# ---------------------------------------------------------------------------


@toolchain_app.command("verify")
def toolchain_verify(
    name: Annotated[str, typer.Argument(help="Toolchain name")],
) -> None:
    """Verify an already-fetched toolchain tarball (not implemented yet)."""
    typer.secho("`toolchain verify` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
