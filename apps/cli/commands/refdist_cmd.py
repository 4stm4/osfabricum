"""Phase 5 — Reference Distribution CLI commands (M71/M72/M73)."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum.db.session import sync_session
from osfabricum.refdist import service as svc

refdist_app = typer.Typer(help="Reference distribution catalog queries", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@refdist_app.command("list")
def list_refdists(
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List all seeded reference distributions."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        items = svc.list_reference_distributions(s)
    if not items:
        typer.echo("(no reference distributions seeded)")
        return
    for d in items:
        typer.echo(
            f"{d.name:<16}  class={d.class_name or '-':<18} "
            f"profiles={len(d.profiles)}  pkgs={d.package_count}"
        )


@refdist_app.command("show")
def show_refdist(
    name: Annotated[str, typer.Argument(help="Distribution name (tinywifi|netos|ocultum)")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Show detail for a reference distribution."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        dist = svc.get_reference_distribution(s, name)
        if dist is None:
            typer.echo(f"Not found: {name}", err=True)
            raise typer.Exit(1)
        profiles = svc.list_reference_profiles(s, name)
    typer.echo(f"name:        {dist.name}")
    typer.echo(f"class:       {dist.class_name or '-'}")
    typer.echo(f"description: {dist.description or '-'}")
    typer.echo(f"channel:     {dist.default_channel or '-'}")
    typer.echo(f"packages:    {dist.package_count}")
    typer.echo(f"groups:      {dist.group_count}")
    typer.echo(f"sets:        {dist.set_count}")
    typer.echo(f"profiles ({len(profiles)}):")
    for p in profiles:
        typer.echo(
            f"  {p.name:<18} board={p.board_name or '-':<20} "
            f"kernel={p.kernel_name or '-':<22} "
            f"toolchain={p.toolchain_name or '-'}"
        )
        if p.packages:
            typer.echo(f"    packages: {', '.join(p.packages)}")


@refdist_app.command("profiles")
def list_profiles(
    name: Annotated[str, typer.Argument(help="Distribution name")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List profiles for a reference distribution."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        profiles = svc.list_reference_profiles(s, name)
    if not profiles:
        typer.echo(f"(no profiles for '{name}')")
        return
    for p in profiles:
        typer.echo(f"{p.name:<20} set={p.package_set_name or '-'}")


@refdist_app.command("validate")
def validate_refdist(
    name: Annotated[str, typer.Argument(help="Distribution name to validate")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Validate that a reference distribution is fully seeded."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        result = svc.validate_reference_distribution(s, name)
    valid = result.get("valid", False)
    typer.echo(f"{'OK' if valid else 'FAIL'}  {name}")
    if not valid:
        for err in result.get("errors", []):
            typer.echo(f"  ERROR: {err}", err=True)
        raise typer.Exit(1)
    typer.echo(
        f"  profiles={result['profiles']}  "
        f"groups={result['groups']}  "
        f"packages={result['packages']}"
    )
