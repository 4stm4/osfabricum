"""M65 — Size / Footprint Optimizer CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import sizeopt as size_svc
from osfabricum.db.session import sync_session

sizeopt_app = typer.Typer(help="Size budgets and footprint analysis", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@sizeopt_app.command("budget")
def set_budget(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    budget_kind: Annotated[str, typer.Option("--kind", help="image|rootfs|package-set|kernel|initramfs|apps")] = "image",
    budget_bytes: Annotated[int, typer.Option("--bytes", help="Budget in bytes")] = 536870912,
    hard_limit: Annotated[bool, typer.Option("--hard/--soft")] = False,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Set a size budget for a profile."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            b = size_svc.set_size_budget(
                s, profile_id=profile_id,
                budget_kind=budget_kind,
                budget_bytes=budget_bytes,
                is_hard_limit=hard_limit,
            )
            s.commit()
            s.refresh(b)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    limit_str = "HARD" if b.is_hard_limit else "soft"
    typer.echo(f"budget: {b.id}  kind={b.budget_kind}  bytes={b.budget_bytes}  [{limit_str}]")


@sizeopt_app.command("report")
def size_report(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    profile_id: Annotated[str | None, typer.Option("--profile")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Analyze size for a build."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        r = size_svc.analyze_size(s, build_id=build_id, profile_id=profile_id)
        s.commit()
        s.refresh(r)
    typer.echo(f"size-report: {r.id}  hash={r.content_hash or '—'}")
    if r.rendered_report:
        typer.echo(r.rendered_report)


@sizeopt_app.command("budgets")
def list_budgets(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List size budgets for a profile."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        budgets = size_svc.list_size_budgets(s, profile_id=profile_id)
    if not budgets:
        typer.echo("(no budgets set)")
        return
    for b in budgets:
        typer.echo(f"{b.budget_kind}: {b.budget_bytes} bytes  {'HARD' if b.is_hard_limit else 'soft'}")
