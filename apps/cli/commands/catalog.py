"""Real implementations of ``osfabricumctl catalog`` subcommands (M2)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Architecture, Board, Distribution
from osfabricum.db.session import sync_session

catalog_app = typer.Typer(help="Browse and manage the registry", no_args_is_help=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        typer.echo(f"ERROR: {path} does not contain a YAML mapping", err=True)
        raise typer.Exit(code=1)
    return data


# ---------------------------------------------------------------------------
# catalog import
# ---------------------------------------------------------------------------


def _import_architectures(items: list[dict[str, Any]], db_url: str | None) -> int:
    count = 0
    with sync_session(db_url) as session:
        for item in items:
            name = item["name"]
            existing = session.scalar(select(Architecture).where(Architecture.name == name))
            if existing is None:
                session.add(Architecture(name=name))
                count += 1
        session.commit()
    return count


def _import_boards(items: list[dict[str, Any]], db_url: str | None) -> int:
    count = 0
    with sync_session(db_url) as session:
        for item in items:
            name = item["name"]
            arch_name = item["arch"]
            arch = session.scalar(select(Architecture).where(Architecture.name == arch_name))
            if arch is None:
                typer.echo(
                    f"ERROR: architecture '{arch_name}' not found — import architectures first.",
                    err=True,
                )
                raise typer.Exit(code=1)
            existing = session.scalar(select(Board).where(Board.name == name))
            if existing is None:
                session.add(
                    Board(
                        name=name,
                        arch_id=arch.id,
                        boot_scheme=item.get("boot_scheme", "unknown"),
                        firmware_required=item.get("firmware_required", False),
                        metadata_json=item.get("metadata"),
                    )
                )
                count += 1
        session.commit()
    return count


def _import_distributions(items: list[dict[str, Any]], db_url: str | None) -> int:
    count = 0
    with sync_session(db_url) as session:
        for item in items:
            name = item["name"]
            existing = session.scalar(select(Distribution).where(Distribution.name == name))
            if existing is None:
                session.add(
                    Distribution(
                        name=name,
                        description=item.get("description"),
                        default_channel=item.get("default_channel", "dev"),
                    )
                )
                count += 1
        session.commit()
    return count


@catalog_app.command(name="import")
def catalog_import(
    file: Annotated[Path, typer.Option("--file", "-f", help="YAML catalog file to import")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Import catalog data (architectures / boards / distributions) from a YAML file."""
    if not file.exists():
        typer.echo(f"ERROR: file not found: {file}", err=True)
        raise typer.Exit(code=1)

    data = _load_yaml(file)
    kind: str = data.get("kind", "")
    items: list[dict[str, Any]] = data.get("items", [])

    try:
        if kind == "ArchitectureList":
            n = _import_architectures(items, db_url)
            typer.echo(f"Imported {n} architecture(s) from {file.name}")
        elif kind == "BoardList":
            n = _import_boards(items, db_url)
            typer.echo(f"Imported {n} board(s) from {file.name}")
        elif kind == "DistributionList":
            n = _import_distributions(items, db_url)
            typer.echo(f"Imported {n} distribution(s) from {file.name}")
        else:
            typer.echo(f"ERROR: unknown kind '{kind}'", err=True)
            raise typer.Exit(code=1)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# catalog list
# ---------------------------------------------------------------------------


def _list_distributions(db_url: str | None) -> None:
    with sync_session(db_url) as session:
        rows = session.scalars(select(Distribution).order_by(Distribution.name)).all()
    tbl = Table("Name", "Description", "Channel", title="Distributions")
    for r in rows:
        tbl.add_row(r.name, r.description or "", r.default_channel)
    Console().print(tbl)


def _list_boards(db_url: str | None) -> None:
    with sync_session(db_url) as session:
        rows = session.scalars(select(Board).order_by(Board.name)).all()
        arch_map = {a.id: a.name for a in session.scalars(select(Architecture)).all()}
    tbl = Table("Name", "Arch", "Boot scheme", "Firmware", title="Boards")
    for r in rows:
        tbl.add_row(
            r.name,
            arch_map.get(r.arch_id, r.arch_id),
            r.boot_scheme,
            "yes" if r.firmware_required else "no",
        )
    Console().print(tbl)


@catalog_app.command("list")
def catalog_list(
    what: Annotated[
        str,
        typer.Argument(help="What to list: distributions | boards | profiles | packages"),
    ],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """List catalog items."""
    try:
        if what == "distributions":
            _list_distributions(db_url)
        elif what == "boards":
            _list_boards(db_url)
        else:
            typer.secho(
                f"`catalog list {what}` is not implemented yet", fg=typer.colors.YELLOW, err=True
            )
            raise typer.Exit(code=1)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# catalog show  (stub — M2 scope is list only)
# ---------------------------------------------------------------------------


@catalog_app.command("show")
def catalog_show(
    kind: Annotated[str, typer.Argument(help="distribution | board | profile")],
    name: Annotated[str, typer.Argument(help="Item name")],
) -> None:
    """Show details for a single catalog item."""
    typer.secho("`catalog show` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
