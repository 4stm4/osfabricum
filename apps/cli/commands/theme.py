"""``osfabricumctl theme`` — Themes / Icons / Fonts Designer CLI (M43)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import theme as th

theme_app = typer.Typer(
    help="Manage theme / appearance profiles (M43)", no_args_is_help=True
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


@theme_app.command("kind-list")
def kind_list(db_url: _DbUrl = None) -> None:
    """List seeded theme asset kinds."""
    items = th.list_theme_asset_kinds(db_url=db_url)
    t = Table(title="Theme Asset Kinds")
    t.add_column("#", style="dim")
    t.add_column("Name")
    t.add_column("Description")
    for k in items:
        t.add_row(str(k["display_order"]), k["name"], k["description"])
    _console.print(t)


@theme_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None, typer.Option("--distribution-id", "-d")
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List theme profiles."""
    profiles = th.list_theme_profiles(distribution_id, db_url=db_url)
    t = Table(title="Theme Profiles")
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("GTK Theme")
    t.add_column("Icons")
    t.add_column("Dark")
    t.add_column("Font")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p["gtk_theme"],
            p["icon_theme"],
            "✓" if p["dark_mode"] else "",
            f"{p['font_default']} {p['font_size']}",
        )
    _console.print(t)


@theme_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[str | None, typer.Option("--distribution-id", "-d")] = None,
    gtk_theme: Annotated[str, typer.Option("--gtk-theme")] = "Adwaita",
    icon_theme: Annotated[str, typer.Option("--icon-theme")] = "Adwaita",
    cursor_theme: Annotated[str, typer.Option("--cursor-theme")] = "Adwaita",
    dark_mode: Annotated[bool, typer.Option("--dark/--light")] = False,
    font_default: Annotated[str, typer.Option("--font")] = "Sans",
    font_monospace: Annotated[str, typer.Option("--font-mono")] = "Monospace",
    font_size: Annotated[int, typer.Option("--font-size")] = 11,
    cursor_size: Annotated[int, typer.Option("--cursor-size")] = 24,
    scaling_factor: Annotated[float, typer.Option("--scaling")] = 1.0,
    db_url: _DbUrl = None,
) -> None:
    """Create a new theme profile."""
    try:
        result = th.create_theme_profile(
            name,
            distribution_id=distribution_id,
            gtk_theme=gtk_theme,
            icon_theme=icon_theme,
            cursor_theme=cursor_theme,
            dark_mode=dark_mode,
            font_default=font_default,
            font_monospace=font_monospace,
            font_size=font_size,
            cursor_size=cursor_size,
            scaling_factor=scaling_factor,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@theme_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of a theme profile."""
    try:
        result = th.get_theme_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@theme_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    gtk_theme: Annotated[str | None, typer.Option("--gtk-theme")] = None,
    icon_theme: Annotated[str | None, typer.Option("--icon-theme")] = None,
    cursor_theme: Annotated[str | None, typer.Option("--cursor-theme")] = None,
    dark_mode: Annotated[bool | None, typer.Option("--dark/--light")] = None,
    font_default: Annotated[str | None, typer.Option("--font")] = None,
    font_monospace: Annotated[str | None, typer.Option("--font-mono")] = None,
    font_size: Annotated[int | None, typer.Option("--font-size")] = None,
    cursor_size: Annotated[int | None, typer.Option("--cursor-size")] = None,
    scaling_factor: Annotated[float | None, typer.Option("--scaling")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update theme fields (clears rendered cache)."""
    try:
        result = th.update_theme_profile(
            profile_id,
            gtk_theme=gtk_theme,
            icon_theme=icon_theme,
            cursor_theme=cursor_theme,
            dark_mode=dark_mode,
            font_default=font_default,
            font_monospace=font_monospace,
            font_size=font_size,
            cursor_size=cursor_size,
            scaling_factor=scaling_factor,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@theme_app.command("pkg-add")
def pkg_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    asset_kind: Annotated[str, typer.Option("--kind", "-k")],
    package_name: Annotated[str, typer.Option("--package", "-p")],
    version_constraint: Annotated[str | None, typer.Option("--version")] = None,
    is_default: Annotated[bool, typer.Option("--default")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add a theme/icon/font package to a profile."""
    try:
        result = th.add_theme_package(
            profile_id,
            asset_kind,
            package_name,
            version_constraint=version_constraint,
            is_default=is_default,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@theme_app.command("gsetting-set")
def gsetting_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    schema: Annotated[str, typer.Option("--schema", "-s")],
    key: Annotated[str, typer.Option("--key", "-k")],
    value: Annotated[str, typer.Option("--value", "-v")],
    description: Annotated[str | None, typer.Option("--description")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Set/upsert a dconf/gsettings key override."""
    try:
        result = th.set_gsettings_override(
            profile_id, schema, key, value, description=description, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@theme_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Generate dconf override + GTK settings.ini and store on profile."""
    try:
        result = th.render_theme_config(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _console.print(f"[green]✓[/green] content_hash: {result['content_hash']}")
    _console.print(
        f"   packages={result['package_count']}  "
        f"gsettings_overrides={result['gsettings_override_count']}"
    )
    _console.rule("dconf override")
    _console.print(result["rendered_gsettings"])
    _console.rule("gtk settings.ini")
    _console.print(result["rendered_gtk_ini"])
