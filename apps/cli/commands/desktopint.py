"""``osfabricumctl desktopint`` — Desktop Integration Designer CLI (M42)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import desktopint as di

desktopint_app = typer.Typer(
    help="Manage desktop integration profiles (M42)", no_args_is_help=True
)

_DbUrl = Annotated[
    str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
]

_console = Console()


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _print_json(data: Any) -> None:
    _console.print_json(json.dumps(data, default=str))


# ---------------------------------------------------------------------------
# MIME type reference
# ---------------------------------------------------------------------------


@desktopint_app.command("mime-list")
def mime_list(db_url: _DbUrl = None) -> None:
    """List seeded MIME type definitions."""
    items = di.list_mime_types(db_url=db_url)
    t = Table(title="MIME Types")
    t.add_column("#", style="dim")
    t.add_column("MIME Type")
    t.add_column("Description")
    t.add_column("Parent")
    for m in items:
        t.add_row(
            str(m["display_order"]),
            m["name"],
            m["description"],
            m["parent"] or "—",
        )
    _console.print(t)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@desktopint_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d", help="Filter by distribution ID"),
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List desktop integration profiles."""
    profiles = di.list_desktop_integration_profiles(distribution_id, db_url=db_url)
    t = Table(title="Desktop Integration Profiles")
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("Distribution")
    t.add_column("Hash")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p["distribution_id"] or "—",
            (p["content_hash"] or "")[:16] or "—",
        )
    _console.print(t)


@desktopint_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[
        str | None, typer.Option("--distribution-id", "-d")
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new desktop integration profile."""
    try:
        result = di.create_desktop_integration_profile(
            name, distribution_id=distribution_id, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@desktopint_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of a desktop integration profile."""
    try:
        result = di.get_desktop_integration_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@desktopint_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    xdg_data_dirs: Annotated[
        str, typer.Option("--xdg-data-dirs", help="Colon-separated XDG_DATA_DIRS")
    ] = "",
    xdg_config_dirs: Annotated[
        str, typer.Option("--xdg-config-dirs", help="Colon-separated XDG_CONFIG_DIRS")
    ] = "",
    db_url: _DbUrl = None,
) -> None:
    """Update XDG path lists (clears rendered cache)."""
    data = [d for d in xdg_data_dirs.split(":") if d.strip()]
    config = [d for d in xdg_config_dirs.split(":") if d.strip()]
    try:
        result = di.update_desktop_integration_profile(
            profile_id,
            xdg_data_dirs=data or None,
            xdg_config_dirs=config or None,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# MIME associations
# ---------------------------------------------------------------------------


@desktopint_app.command("mime-add")
def mime_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    mime_type: Annotated[str, typer.Option("--mime", "-m")],
    desktop_file: Annotated[str, typer.Option("--desktop", "-d")],
    association_type: Annotated[
        str, typer.Option("--type", "-t", help="default | added | removed")
    ] = "default",
    priority: Annotated[int, typer.Option("--priority")] = 0,
    db_url: _DbUrl = None,
) -> None:
    """Add a MIME type → .desktop file association."""
    try:
        result = di.add_mime_association(
            profile_id,
            mime_type,
            desktop_file,
            association_type=association_type,
            priority=priority,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------


@desktopint_app.command("autostart-add")
def autostart_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n")],
    exec_cmd: Annotated[str, typer.Option("--exec", "-e")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    condition: Annotated[
        str, typer.Option("--condition", "-c", help="always | graphical | wayland | x11")
    ] = "always",
    disabled: Annotated[bool, typer.Option("--disabled")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add an XDG autostart entry."""
    try:
        result = di.add_autostart_entry(
            profile_id,
            name,
            exec_cmd,
            comment=comment,
            condition=condition,
            is_enabled=not disabled,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# XDG user directories
# ---------------------------------------------------------------------------


@desktopint_app.command("userdir-set")
def userdir_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    dir_name: Annotated[
        str, typer.Option("--dir", "-d", help="DESKTOP|DOWNLOAD|DOCUMENTS|…")
    ],
    path: Annotated[str, typer.Option("--path", "-p")],
    db_url: _DbUrl = None,
) -> None:
    """Set an XDG user directory path override."""
    try:
        result = di.set_user_dir(profile_id, dir_name, path, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@desktopint_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Generate mimeapps.list + user-dirs.defaults and store on profile."""
    try:
        result = di.render_desktop_integration(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _console.print(f"[green]✓[/green] content_hash: {result['content_hash']}")
    _console.print(
        f"   assocs={result['association_count']}  "
        f"autostart={result['autostart_count']}  "
        f"user_dirs={result['user_dir_count']}"
    )
    _console.rule("mimeapps.list")
    _console.print(result["rendered_mimeapps"])
    _console.rule("user-dirs.defaults")
    _console.print(result["rendered_user_dirs"])
