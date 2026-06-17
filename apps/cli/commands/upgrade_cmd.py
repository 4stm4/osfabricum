"""M61 — Upgrade Service CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import upgrade as upg_svc
from osfabricum.db.session import sync_session

upgrade_app = typer.Typer(help="OS upgrade requests and results", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@upgrade_app.command("request")
def request_upgrade(
    distribution_id: Annotated[str, typer.Argument(help="Distribution ID")],
    target_channel: Annotated[str, typer.Option("--channel", help="Target channel")] = "stable",
    target_version: Annotated[str | None, typer.Option("--version")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create an upgrade request."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        req = upg_svc.create_upgrade_request(
            s, distribution_id=distribution_id,
            target_channel=target_channel,
            target_version=target_version,
        )
        s.commit()
        s.refresh(req)
    typer.echo(f"upgrade-request: {req.id}  status={req.status}  channel={req.target_channel}")


@upgrade_app.command("list")
def list_upgrades(
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List upgrade requests."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        reqs = upg_svc.list_upgrade_requests(s, distribution_id=distribution_id, status=status)
    if not reqs:
        typer.echo("(no upgrade requests)")
        return
    for r in reqs:
        typer.echo(f"{r.id[:8]}  dist={r.distribution_id or '—'}  status={r.status}  channel={r.target_channel}")


@upgrade_app.command("show")
def show_upgrade(
    upgrade_id: Annotated[str, typer.Argument(help="Upgrade request ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Show upgrade request details."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            req = upg_svc.get_upgrade_request(s, upgrade_id)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"id:      {req.id}")
    typer.echo(f"status:  {req.status}")
    typer.echo(f"channel: {req.target_channel}")
    typer.echo(f"version: {req.target_version or '—'}")
