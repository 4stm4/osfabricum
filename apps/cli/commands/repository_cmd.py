"""M69 — Public Artifact Repository / Release Publishing CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import repository as repo_svc
from osfabricum.db.session import sync_session

repository_app = typer.Typer(help="Release publishing and repository management", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@repository_app.command("list")
def list_releases(
    channel: Annotated[str | None, typer.Option("--channel")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List published releases."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        rels = repo_svc.list_releases(s, channel=channel, status=status)
    if not rels:
        typer.echo("(no releases)")
        return
    for r in rels:
        typer.echo(f"{r.id[:8]}  {r.channel}/{r.version}  status={r.status}")


@repository_app.command("create")
def create_release(
    channel: Annotated[str, typer.Argument(help="Release channel (stable|testing|nightly|lts|dev)")],
    version: Annotated[str, typer.Argument(help="Version string")],
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create a new release draft."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        r = repo_svc.create_release(
            s, channel=channel, version=version,
            distribution_id=distribution_id,
        )
        s.commit()
        s.refresh(r)
    typer.echo(f"release: {r.id}  {r.channel}/{r.version}  status={r.status}")


@repository_app.command("promote")
def promote_release(
    release_id: Annotated[str, typer.Argument(help="Release ID")],
    status: Annotated[str, typer.Option("--status", help="published|withdrawn")] = "published",
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Promote a release to a new status."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            r = repo_svc.promote_release(s, release_id, status)
            s.commit()
            s.refresh(r)
        except (KeyError, ValueError) as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"release: {r.id}  {r.channel}/{r.version}  status={r.status}")


@repository_app.command("show")
def show_release(
    release_id: Annotated[str, typer.Argument(help="Release ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Show release details and manifest."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            r = repo_svc.render_release_manifest(s, release_id)
            s.commit()
            s.refresh(r)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"release: {r.id}  {r.channel}/{r.version}  status={r.status}")
    typer.echo(f"hash: {r.content_hash or '—'}")
    typer.echo(r.rendered_release_manifest or "(no manifest)")


@repository_app.command("repos")
def list_repos(
    repo_kind: Annotated[str | None, typer.Option("--kind")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List repositories."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        repos = repo_svc.list_repositories(s, repo_kind=repo_kind)
    if not repos:
        typer.echo("(no repositories)")
        return
    for r in repos:
        typer.echo(f"{r.id[:8]}  {r.name}  kind={r.repo_kind}  published={'Y' if r.is_published else 'N'}")
