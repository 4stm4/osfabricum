"""Real implementations of ``osfabricumctl store`` subcommands (M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.exc import OperationalError

from osfabricum.settings import load_settings
from osfabricum.store.gc import (
    collect_garbage,
    pin_artifact,
    unpin_artifact,
)
from osfabricum.store.gc import store_stats as _store_stats
from osfabricum.store.verify import verify_store

store_app = typer.Typer(help="Artifact store maintenance", no_args_is_help=True)


def _resolve_store_root(store_root: str | None) -> Path:
    if store_root is None:
        store_root = load_settings().store.root
    return Path(store_root)


_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


@store_app.command("verify")
def store_verify(
    store_root: Annotated[
        str | None,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Store root path"),
    ] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Verify all blobs in the store against their recorded sha256."""
    if store_root is None:
        settings = load_settings()
        store_root = settings.store.root
    root = Path(store_root)
    try:
        ok, errors = verify_store(root, db_url)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    if errors:
        for msg in errors:
            typer.secho(f"ERROR: {msg}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"OK: {ok} blob(s) verified")


@store_app.command("stats")
def store_stats_cmd(
    store_root: Annotated[
        str | None,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Store root path"),
    ] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Show store statistics (artifacts and bytes per retention class)."""
    root = _resolve_store_root(store_root)
    try:
        stats = _store_stats(root, db_url=db_url)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    console = Console()
    tbl = Table("Retention class", "Artifacts", "Bytes", title="Store by class")
    for cls, bucket in sorted(stats.by_class.items()):
        tbl.add_row(cls, str(bucket["count"]), f"{bucket['bytes']:,}")
    console.print(tbl)
    console.print(
        f"Total: [bold]{stats.total_artifacts}[/bold] artifacts, "
        f"[bold]{stats.total_bytes:,}[/bold] bytes "
        f"({stats.pinned} pinned)"
    )
    console.print(
        f"Blobs on disk: {stats.blob_files} ([yellow]{stats.orphan_blobs} orphan[/yellow])"
    )


@store_app.command("gc")
def store_gc(
    store_root: Annotated[
        str | None,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Store root path"),
    ] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would be deleted; touch nothing")
    ] = False,
    quota_mb: Annotated[
        int | None, typer.Option("--quota-mb", help="cache-hot quota in MiB (LRU eviction)")
    ] = None,
) -> None:
    """Run garbage collection: expire old artifacts and sweep orphan blobs."""
    root = _resolve_store_root(store_root)
    quota_bytes = quota_mb * 1024 * 1024 if quota_mb is not None else None
    try:
        result = collect_garbage(root, db_url=db_url, dry_run=dry_run, quota_bytes=quota_bytes)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    console = Console()
    for line in result.logs:
        console.print(f"  {line}")
    prefix = "[yellow]would free[/yellow]" if dry_run else "[green]freed[/green]"
    console.print(
        f"{prefix} {result.freed_bytes:,} bytes — "
        f"{len(result.deleted_artifacts)} artifact(s), "
        f"{result.orphan_blobs_removed} orphan blob(s)"
    )


@store_app.command("pin")
def store_pin(
    artifact_id: Annotated[str, typer.Argument(help="Artifact ID to pin")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Pin an artifact so GC never collects it."""
    if pin_artifact(artifact_id, db_url=db_url):
        typer.echo(f"Pinned {artifact_id}")
    else:
        typer.echo(f"ERROR: artifact not found: {artifact_id}", err=True)
        raise typer.Exit(code=1)


@store_app.command("unpin")
def store_unpin(
    artifact_id: Annotated[str, typer.Argument(help="Artifact ID to unpin")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Unpin an artifact, making it eligible for GC again."""
    if unpin_artifact(artifact_id, db_url=db_url):
        typer.echo(f"Unpinned {artifact_id}")
    else:
        typer.echo(f"ERROR: artifact not found: {artifact_id}", err=True)
        raise typer.Exit(code=1)
