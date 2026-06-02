"""``osfabricumctl distribution`` — Distribution Designer CLI (M26).

A thin client over ``osfabricum.distribution`` (the same service the REST API
uses). Works for any distribution; there is no reference-distribution special
case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
import yaml
from rich.console import Console
from rich.table import Table
from sqlalchemy.exc import OperationalError

from osfabricum import distribution as dist_service

distribution_app = typer.Typer(help="Create and manage distributions (M26)", no_args_is_help=True)

_DbUrl = Annotated[
    str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
]
_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _print_distribution(data: dict[str, Any]) -> None:
    console = Console()
    console.print(
        f"[bold]{data['name']}[/bold]  "
        f"(class={data.get('class') or '—'}, channel={data['default_channel']})"
    )
    if data.get("description"):
        console.print(data["description"])
    profiles = data.get("profiles", [])
    if profiles:
        tbl = Table("Profile", "Inherits", "Class", title="Profiles")
        for p in profiles:
            tbl.add_row(p["name"], p.get("inherits") or "—", p.get("class") or "—")
        console.print(tbl)
    else:
        console.print("[dim]no profiles[/dim]")


@distribution_app.command("list")
def list_cmd(db_url: _DbUrl = None) -> None:
    """List distributions."""
    try:
        rows = dist_service.list_distributions(db_url=db_url)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    tbl = Table("Name", "Class", "Channel", "Profiles", "Description", title="Distributions")
    for d in rows:
        tbl.add_row(
            d["name"],
            d.get("class") or "—",
            d["default_channel"],
            str(d["profile_count"]),
            d.get("description") or "",
        )
    Console().print(tbl)


@distribution_app.command("show")
def show_cmd(name: str, db_url: _DbUrl = None) -> None:
    """Show a distribution and its profiles."""
    try:
        _print_distribution(dist_service.get_distribution(name, db_url=db_url))
    except ValueError as exc:
        _fail(str(exc))
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None


@distribution_app.command("create")
def create_cmd(
    name: str,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    channel: Annotated[str, typer.Option("--channel")] = "dev",
    distribution_class: Annotated[str | None, typer.Option("--class")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new distribution."""
    try:
        data = dist_service.create_distribution(
            name=name,
            description=description,
            default_channel=channel,
            class_name=distribution_class,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Created distribution '{name}'", fg=typer.colors.GREEN)
    _print_distribution(data)


@distribution_app.command("edit")
def edit_cmd(
    name: str,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    channel: Annotated[str | None, typer.Option("--channel")] = None,
    distribution_class: Annotated[str | None, typer.Option("--class")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update a distribution's description / channel / class."""
    kwargs: dict[str, object] = {}
    if description is not None:
        kwargs["description"] = description
    if channel is not None:
        kwargs["default_channel"] = channel
    if distribution_class is not None:
        kwargs["class_name"] = distribution_class
    if not kwargs:
        _fail("nothing to update (pass --description / --channel / --class)")
    try:
        data = dist_service.update_distribution(name, db_url=db_url, **kwargs)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Updated distribution '{name}'", fg=typer.colors.GREEN)
    _print_distribution(data)


@distribution_app.command("clone")
def clone_cmd(source: str, new_name: str, db_url: _DbUrl = None) -> None:
    """Clone a distribution (with its profiles) under a new name."""
    try:
        data = dist_service.clone_distribution(source, new_name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Cloned '{source}' -> '{new_name}'", fg=typer.colors.GREEN)
    _print_distribution(data)


@distribution_app.command("delete")
def delete_cmd(
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Delete a distribution (and its profiles)."""
    if not yes and not typer.confirm(f"Delete distribution '{name}' and its profiles?"):
        raise typer.Abort()
    try:
        dist_service.delete_distribution(name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Deleted distribution '{name}'", fg=typer.colors.GREEN)


@distribution_app.command(name="import")
def import_cmd(
    file: Annotated[Path, typer.Option("--file", "-f", help="Distribution YAML to import")],
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace if it exists")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Import a distribution from a YAML document."""
    if not file.exists():
        _fail(f"file not found: {file}")
    with file.open() as fh:
        data = yaml.safe_load(fh)
    try:
        result = dist_service.import_distribution(data, db_url=db_url, overwrite=overwrite)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Imported distribution '{result['name']}'", fg=typer.colors.GREEN)
    _print_distribution(result)


@distribution_app.command("export")
def export_cmd(
    name: str,
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Write YAML here")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Export a distribution to a YAML document (stdout or --file)."""
    try:
        doc = dist_service.export_distribution(name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    text = yaml.safe_dump(doc, sort_keys=False)
    if file is not None:
        file.write_text(text)
        typer.secho(f"Exported '{name}' -> {file}", fg=typer.colors.GREEN, err=True)
    else:
        typer.echo(text)
