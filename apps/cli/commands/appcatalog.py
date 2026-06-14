"""``osfabricumctl appcatalog`` — Application Catalog Designer CLI (M41)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import appcatalog as ac

appcatalog_app = typer.Typer(
    help="Manage application catalog profiles (M41)", no_args_is_help=True
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
# Categories
# ---------------------------------------------------------------------------


@appcatalog_app.command("category-list")
def category_list(db_url: _DbUrl = None) -> None:
    """List all seeded application categories."""
    items = ac.list_app_categories(db_url=db_url)
    t = Table(title="App Categories")
    t.add_column("#", style="dim")
    t.add_column("Name")
    t.add_column("Description")
    for c in items:
        t.add_row(str(c["display_order"]), c["name"], c["description"])
    _console.print(t)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@appcatalog_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d", help="Filter by distribution ID"),
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List app catalog profiles."""
    profiles = ac.list_catalog_profiles(distribution_id, db_url=db_url)
    t = Table(title="App Catalog Profiles")
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


@appcatalog_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[
        str | None, typer.Option("--distribution-id", "-d")
    ] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new app catalog profile."""
    try:
        result = ac.create_catalog_profile(
            name,
            distribution_id=distribution_id,
            description=description,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@appcatalog_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of an app catalog profile."""
    try:
        result = ac.get_catalog_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@appcatalog_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    description: Annotated[str | None, typer.Option("--description")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update catalog metadata (clears rendered cache)."""
    try:
        result = ac.update_catalog_profile(
            profile_id,
            description=description,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


@appcatalog_app.command("app-add")
def app_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="App internal name")],
    display_name: Annotated[str, typer.Option("--display-name")],
    package_name: Annotated[str, typer.Option("--package", "-p")],
    category: Annotated[str, typer.Option("--category", "-c")] = "utilities",
    description: Annotated[str | None, typer.Option("--description")] = None,
    version_constraint: Annotated[
        str | None, typer.Option("--version-constraint")
    ] = None,
    icon_name: Annotated[str | None, typer.Option("--icon")] = None,
    no_default: Annotated[
        bool, typer.Option("--no-default", help="Do not mark as default install")
    ] = False,
    optional: Annotated[bool, typer.Option("--optional")] = False,
    tags: Annotated[str, typer.Option("--tags", help="Comma-separated tags")] = "",
    db_url: _DbUrl = None,
) -> None:
    """Add an application to a catalog profile."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        result = ac.add_app(
            profile_id,
            name,
            display_name,
            package_name,
            description=description,
            category_name=category,
            version_constraint=version_constraint,
            icon_name=icon_name,
            is_default_install=not no_default,
            is_optional=optional,
            tags=tag_list,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@appcatalog_app.command("group-add")
def group_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n")],
    description: Annotated[str | None, typer.Option("--description")] = None,
    is_default: Annotated[bool, typer.Option("--default")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add a named app group to a catalog profile."""
    try:
        result = ac.add_group(
            profile_id,
            name,
            description=description,
            is_default=is_default,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@appcatalog_app.command("member-add")
def member_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    group_name: Annotated[str, typer.Option("--group", "-g")],
    app_name: Annotated[str, typer.Option("--app", "-a")],
    position: Annotated[int, typer.Option("--position")] = 0,
    db_url: _DbUrl = None,
) -> None:
    """Add an app to a group."""
    try:
        result = ac.add_group_member(
            profile_id,
            group_name,
            app_name,
            position=position,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Default roles
# ---------------------------------------------------------------------------


@appcatalog_app.command("role-set")
def role_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    role: Annotated[str, typer.Option("--role", "-r")],
    app_name: Annotated[str, typer.Option("--app", "-a")],
    package_name: Annotated[str, typer.Option("--package", "-p")],
    db_url: _DbUrl = None,
) -> None:
    """Bind a functional role to an app (e.g. web-browser → firefox)."""
    try:
        result = ac.set_default_role(
            profile_id,
            role,
            app_name,
            package_name,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@appcatalog_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Generate deterministic app-list manifest and store on profile."""
    try:
        result = ac.render_app_list(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _console.print(f"[green]✓[/green] content_hash: {result['content_hash']}")
    _console.print(
        f"   apps={result['app_count']}  groups={result['group_count']}  "
        f"roles={result['role_count']}"
    )
    _console.print(result["rendered_app_list"])
