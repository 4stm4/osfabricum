"""M62 — Lockfile Manager CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import lockfile as lf_svc
from osfabricum.db.session import sync_session

lockfile_app = typer.Typer(help="Lockfile generation and diffing", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@lockfile_app.command("generate")
def generate_lockfile(
    distribution_id: Annotated[str, typer.Option("--dist", help="Distribution ID")],
    profile_id: Annotated[str | None, typer.Option("--profile")] = None,
    build_id: Annotated[str | None, typer.Option("--build")] = None,
    lock_version: Annotated[str, typer.Option("--lock-version")] = "1",
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create a new lockfile."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        lf = lf_svc.create_lockfile(
            s, distribution_id=distribution_id,
            profile_id=profile_id, build_id=build_id,
            lock_version=lock_version,
        )
        s.commit()
        s.refresh(lf)
    typer.echo(f"lockfile: {lf.id}  version={lf.lock_version}")


@lockfile_app.command("render")
def render_lockfile(
    lockfile_id: Annotated[str, typer.Argument(help="Lockfile ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Render lockfile as INI text."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            lf = lf_svc.render_lockfile(s, lockfile_id)
            s.commit()
            s.refresh(lf)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(lf.rendered_lock or "(empty)")


@lockfile_app.command("diff")
def diff_lockfiles(
    lockfile_a: Annotated[str, typer.Argument(help="Lockfile A ID")],
    lockfile_b: Annotated[str, typer.Argument(help="Lockfile B ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Diff two lockfiles."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            result = lf_svc.diff_lockfiles(s, lockfile_a, lockfile_b)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    for key in ("added", "removed", "changed"):
        items = result.get(key, {})
        if items:
            typer.echo(f"\n[{key}]")
            for k, v in items.items():
                typer.echo(f"  {k} = {v}")


@lockfile_app.command("list")
def list_lockfiles(
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List lockfiles."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        lfs = lf_svc.list_lockfiles(s, distribution_id=distribution_id)
    if not lfs:
        typer.echo("(no lockfiles)")
        return
    for lf in lfs:
        typer.echo(f"{lf.id[:8]}  dist={lf.distribution_id or '—'}  v={lf.lock_version}  hash={lf.content_hash or '—'}")
