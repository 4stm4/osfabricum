"""M66 — Boot / Performance Profiler CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import bootprofiler as bp_svc
from osfabricum.db.session import sync_session

bootprofiler_app = typer.Typer(help="Boot performance profiling", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@bootprofiler_app.command("capture")
def capture(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    method: Annotated[str, typer.Option("--method", help="qemu|serial|journal")] = "qemu",
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create a boot profile for a build."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            p = bp_svc.create_boot_profile(s, build_id=build_id, capture_method=method)
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"boot-profile: {p.id}  method={p.capture_method}")


@bootprofiler_app.command("render")
def render_timeline(
    profile_id: Annotated[str, typer.Argument(help="Boot profile ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Render boot timeline."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            p = bp_svc.render_boot_timeline(s, profile_id)
            s.commit()
            s.refresh(p)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"total_boot_ms: {p.total_boot_ms}")
    typer.echo(p.rendered_timeline or "(no samples)")


@bootprofiler_app.command("list")
def list_profiles(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List boot profiles for a build."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        profiles = bp_svc.list_boot_profiles(s, build_id=build_id)
    if not profiles:
        typer.echo("(no boot profiles)")
        return
    for p in profiles:
        typer.echo(f"{p.id[:8]}  method={p.capture_method}  boot_ms={p.total_boot_ms}  hash={p.content_hash or '—'}")
