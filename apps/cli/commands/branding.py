"""``osfabricumctl branding`` — Branding / Identity Designer CLI (M39)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import branding as br

branding_app = typer.Typer(
    help="Manage branding profiles and identity assets (M39)", no_args_is_help=True
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
# Profile CRUD
# ---------------------------------------------------------------------------


@branding_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d", help="Filter by distribution ID"),
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List all branding profiles."""
    profiles = br.list_branding_profiles(distribution_id, db_url=db_url)
    if not profiles:
        typer.echo("No branding profiles found.")
        return
    t = Table(title="Branding Profiles")
    t.add_column("ID", no_wrap=True)
    t.add_column("Name")
    t.add_column("OS Name")
    t.add_column("OS ID")
    t.add_column("Version")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p.get("os_name") or "-",
            p.get("os_id") or "-",
            p.get("os_version") or "-",
        )
    _console.print(t)


@branding_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[
        str | None,
        typer.Option("--distribution-id", "-d", help="Distribution ID"),
    ] = None,
    os_name: Annotated[str | None, typer.Option(help="NAME= in os-release")] = None,
    os_id: Annotated[str | None, typer.Option(help="ID= in os-release (no spaces)")] = None,
    os_version: Annotated[str | None, typer.Option(help="VERSION= in os-release")] = None,
    os_pretty_name: Annotated[str | None, typer.Option(help="PRETTY_NAME=")] = None,
    os_home_url: Annotated[str | None, typer.Option(help="HOME_URL=")] = None,
    vendor_name: Annotated[str | None, typer.Option(help="Vendor / company name")] = None,
    vendor_url: Annotated[str | None, typer.Option(help="Vendor URL")] = None,
    support_url: Annotated[str | None, typer.Option(help="SUPPORT_URL=")] = None,
    bug_report_url: Annotated[str | None, typer.Option(help="BUG_REPORT_URL=")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new branding profile."""
    try:
        result = br.create_branding_profile(
            name,
            distribution_id=distribution_id,
            os_name=os_name,
            os_id=os_id,
            os_version=os_version,
            os_pretty_name=os_pretty_name,
            os_home_url=os_home_url,
            vendor_name=vendor_name,
            vendor_url=vendor_url,
            support_url=support_url,
            bug_report_url=bug_report_url,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@branding_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of a branding profile."""
    try:
        result = br.get_branding_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@branding_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    os_name: Annotated[str | None, typer.Option()] = None,
    os_id: Annotated[str | None, typer.Option()] = None,
    os_version: Annotated[str | None, typer.Option()] = None,
    os_pretty_name: Annotated[str | None, typer.Option()] = None,
    os_home_url: Annotated[str | None, typer.Option()] = None,
    vendor_name: Annotated[str | None, typer.Option()] = None,
    vendor_url: Annotated[str | None, typer.Option()] = None,
    support_url: Annotated[str | None, typer.Option()] = None,
    bug_report_url: Annotated[str | None, typer.Option()] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update identity fields of a branding profile."""
    try:
        result = br.update_branding_profile(
            profile_id,
            os_name=os_name,
            os_id=os_id,
            os_version=os_version,
            os_pretty_name=os_pretty_name,
            os_home_url=os_home_url,
            vendor_name=vendor_name,
            vendor_url=vendor_url,
            support_url=support_url,
            bug_report_url=bug_report_url,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Assets & Targets
# ---------------------------------------------------------------------------


@branding_app.command("asset-add")
def asset_add(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    name: Annotated[str, typer.Option("--name", "-n", help="Asset name")],
    kind: Annotated[
        str,
        typer.Option(
            "--kind", "-k", help=f"Asset kind: {', '.join(br.ASSET_KINDS)}"
        ),
    ],
    source_path: Annotated[str | None, typer.Option(help="Source file path")] = None,
    mime_type: Annotated[str | None, typer.Option()] = None,
    width: Annotated[int | None, typer.Option("--width", help="Width in px")] = None,
    height: Annotated[int | None, typer.Option("--height", help="Height in px")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Attach an asset file to a branding profile."""
    try:
        result = br.add_asset(
            profile_id,
            name,
            kind,
            source_path=source_path,
            mime_type=mime_type,
            width_px=width,
            height_px=height,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@branding_app.command("target-set")
def target_set(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    stage: Annotated[
        str,
        typer.Argument(help=f"Build stage: {', '.join(br.BRANDING_STAGES)}"),
    ],
    asset_id: Annotated[str | None, typer.Option("--asset-id")] = None,
    config: Annotated[str | None, typer.Option(help="Config JSON string")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Map a build stage to an asset or config."""
    config_data: dict[str, Any] | None = None
    if config is not None:
        try:
            config_data = json.loads(config)
        except json.JSONDecodeError as exc:
            _fail(f"--config must be valid JSON: {exc}")
    try:
        result = br.set_target(
            profile_id, stage, asset_id=asset_id, config_json=config_data, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@branding_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    what: Annotated[
        str,
        typer.Argument(help="What to render: os-release | motd"),
    ] = "os-release",
    db_url: _DbUrl = None,
) -> None:
    """Render os-release or motd for a branding profile."""
    try:
        if what == "os-release":
            result = br.render_os_release(profile_id, db_url=db_url)
            typer.echo(result["rendered_os_release"])
        elif what == "motd":
            result = br.render_motd(profile_id, db_url=db_url)
            typer.echo(result["rendered_motd"])
        else:
            _fail(f"unknown render target {what!r}; use 'os-release' or 'motd'")
    except ValueError as exc:
        _fail(str(exc))


# ---------------------------------------------------------------------------
# Boot splash / Login theme
# ---------------------------------------------------------------------------


@branding_app.command("boot-splash")
def boot_splash(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    theme_name: Annotated[str, typer.Argument(help="Plymouth theme name")] = "spinner",
    package_name: Annotated[str | None, typer.Option()] = None,
    db_url: _DbUrl = None,
) -> None:
    """Set the Plymouth boot-splash theme."""
    try:
        result = br.set_boot_splash(
            profile_id, theme_name, package_name=package_name, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@branding_app.command("login-theme")
def login_theme(
    profile_id: Annotated[str, typer.Argument(help="Branding profile ID")],
    theme_name: Annotated[str, typer.Argument(help="Greeter theme name")],
    display_manager: Annotated[
        str | None,
        typer.Option("--dm", help="Display manager: lightdm|gdm|sddm|greetd"),
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """Set the display-manager login theme."""
    try:
        result = br.set_login_theme(
            profile_id, theme_name, display_manager=display_manager, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)
