"""``osfabricumctl graphical`` — Graphical Shell Designer CLI (M40)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import graphical as gr

graphical_app = typer.Typer(
    help="Manage graphical shell profiles (M40)", no_args_is_help=True
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
# Backends
# ---------------------------------------------------------------------------


@graphical_app.command("compositor-list")
def compositor_list(db_url: _DbUrl = None) -> None:
    """List all seeded compositor backends."""
    items = gr.list_compositor_backends(db_url=db_url)
    t = Table(title="Compositor Backends")
    t.add_column("Name")
    t.add_column("Protocol")
    t.add_column("Package")
    t.add_column("Description")
    for b in items:
        t.add_row(b["name"], b["protocol"], b["package_name"] or "—", b["description"])
    _console.print(t)


@graphical_app.command("dm-list")
def dm_list(db_url: _DbUrl = None) -> None:
    """List all seeded display manager backends."""
    items = gr.list_display_manager_backends(db_url=db_url)
    t = Table(title="Display Manager Backends")
    t.add_column("Name")
    t.add_column("Package")
    t.add_column("Description")
    for b in items:
        t.add_row(b["name"], b["package_name"] or "—", b["description"])
    _console.print(t)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@graphical_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d", help="Filter by distribution ID"),
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List graphical profiles."""
    profiles = gr.list_graphical_profiles(distribution_id, db_url=db_url)
    if not profiles:
        typer.echo("No graphical profiles found.")
        return
    t = Table(title="Graphical Profiles")
    t.add_column("ID", no_wrap=True)
    t.add_column("Name")
    t.add_column("Display Server")
    t.add_column("Compositor")
    t.add_column("DM")
    t.add_column("Toolkit")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p.get("display_server") or "none",
            p.get("compositor") or "—",
            p.get("display_manager") or "—",
            p.get("toolkit_default") or "—",
        )
    _console.print(t)


@graphical_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d"),
    ] = None,
    display_server: Annotated[
        str, typer.Option(help=f"Display server: {', '.join(gr.DISPLAY_SERVERS)}")
    ] = "none",
    compositor: Annotated[str | None, typer.Option(help="Compositor name")] = None,
    display_manager: Annotated[str | None, typer.Option("--dm")] = None,
    session_manager: Annotated[str | None, typer.Option("--session-manager")] = None,
    toolkit: Annotated[
        str | None, typer.Option("--toolkit", help="Default toolkit: gtk3/gtk4/qt5/qt6")
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new graphical shell profile."""
    try:
        result = gr.create_graphical_profile(
            name,
            distribution_id=distribution_id,
            display_server=display_server,
            compositor=compositor,
            display_manager=display_manager,
            session_manager=session_manager,
            toolkit_default=toolkit,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@graphical_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Graphical profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full graphical profile details."""
    try:
        result = gr.get_graphical_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@graphical_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Graphical profile ID")],
    display_server: Annotated[str | None, typer.Option()] = None,
    compositor: Annotated[str | None, typer.Option()] = None,
    display_manager: Annotated[str | None, typer.Option("--dm")] = None,
    session_manager: Annotated[str | None, typer.Option("--session-manager")] = None,
    toolkit: Annotated[str | None, typer.Option("--toolkit")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update a graphical profile's stack settings."""
    try:
        result = gr.update_graphical_profile(
            profile_id,
            display_server=display_server,
            compositor=compositor,
            display_manager=display_manager,
            session_manager=session_manager,
            toolkit_default=toolkit,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


@graphical_app.command("component-add")
def component_add(
    profile_id: Annotated[str, typer.Argument(help="Graphical profile ID")],
    kind: Annotated[
        str,
        typer.Option("--kind", "-k", help=f"Component kind: {', '.join(gr.COMPONENT_KINDS)}"),
    ],
    package: Annotated[str, typer.Option("--package", "-p", help="Package name")],
    version: Annotated[str | None, typer.Option("--version", help="Version constraint")] = None,
    optional: Annotated[bool, typer.Option("--optional")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add a component package to a graphical profile."""
    try:
        result = gr.add_component(
            profile_id,
            kind,
            package,
            version_constraint=version,
            is_required=not optional,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@graphical_app.command("session-add")
def session_add(
    profile_id: Annotated[str, typer.Argument(help="Graphical profile ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="Session name")],
    session_type: Annotated[
        str,
        typer.Option(
            "--type", "-t", help=f"Session type: {', '.join(gr.SESSION_TYPES)}"
        ),
    ] = "wayland",
    exec_cmd: Annotated[str | None, typer.Option("--exec")] = None,
    default: Annotated[bool, typer.Option("--default")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add a session entry to a graphical profile."""
    try:
        result = gr.add_session(
            profile_id,
            name,
            session_type,
            exec_cmd=exec_cmd,
            is_default=default,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@graphical_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Graphical profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Render the .desktop session config for a graphical profile."""
    try:
        result = gr.render_session_config(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.echo(result["rendered_session_config"])
    typer.secho(f"# {result['content_hash']}", fg=typer.colors.BRIGHT_BLACK)
