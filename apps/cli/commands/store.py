"""Real implementations of ``osfabricumctl store`` subcommands (M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from sqlalchemy.exc import OperationalError

from osfabricum.settings import load_settings
from osfabricum.store.verify import verify_store

store_app = typer.Typer(help="Artifact store maintenance", no_args_is_help=True)

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
def store_stats() -> None:
    """Show store statistics."""
    typer.secho("`store stats` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@store_app.command("gc")
def store_gc() -> None:
    """Run garbage collection on the store."""
    typer.secho("`store gc` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
