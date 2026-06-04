"""``osfabricumctl builds`` subcommands (M18)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Board, Distribution, Profile
from osfabricum.db.session import sync_session
from osfabricum.pipeline.log import get_build_logs, search_builds
from osfabricum.pipeline.record import get_build, list_build_events, list_build_jobs, list_builds

builds_app = typer.Typer(help="Inspect and manage builds", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


def _resolve_names(build, db_url: str | None) -> tuple[str, str, str]:
    """Return (distribution_name, profile_name, board_name) for a Build row."""
    with sync_session(db_url) as session:
        dist = session.scalar(select(Distribution).where(Distribution.id == build.distribution_id))
        prof = session.scalar(select(Profile).where(Profile.id == build.profile_id))
        board = session.scalar(select(Board).where(Board.id == build.board_id))
    return (
        dist.name if dist else build.distribution_id[:8],
        prof.name if prof else build.profile_id[:8],
        board.name if board else build.board_id[:8],
    )


@builds_app.command("list")
def builds_list(
    limit: Annotated[int, typer.Option("--limit", help="Max rows to show")] = 20,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter: success|failed|running")
    ] = None,
    distribution: Annotated[
        str | None, typer.Option("--distribution", "-d", help="Filter by distribution name")
    ] = None,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """List recent builds (with optional filters)."""
    try:
        if status is not None or distribution is not None:
            builds = search_builds(
                distribution_name=distribution,
                status=status,
                limit=limit,
                db_url=db_url,
            )
        else:
            builds = list_builds(limit=limit, db_url=db_url)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    tbl = Table("ID", "Distribution", "Profile", "Board", "Status", "Created", title="Builds")
    for b in builds:
        try:
            dist_name, prof_name, board_name = _resolve_names(b, db_url)
        except Exception:
            dist_name = prof_name = board_name = "?"
        created = b.created_at.strftime("%Y-%m-%d %H:%M:%S") if b.created_at else ""
        status_color = {
            "success": "green",
            "failed": "red",
            "running": "yellow",
            "queued": "cyan",
        }.get(b.status, "white")
        tbl.add_row(
            b.id[:8],
            dist_name,
            prof_name,
            board_name,
            f"[{status_color}]{b.status}[/{status_color}]",
            created,
        )
    Console().print(tbl)


@builds_app.command("show")
def builds_show(
    build_id: Annotated[str, typer.Argument(help="Build ID (full or 8-char prefix)")],
    show_logs: Annotated[
        bool, typer.Option("--logs", help="Also print captured log lines")
    ] = False,
    log_limit: Annotated[int, typer.Option("--log-limit", help="Max log lines to show")] = 100,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Show details, jobs, and optionally log lines for a build."""
    try:
        build = get_build(build_id, db_url=db_url)
        if build is None:
            # Try prefix match
            builds = list_builds(limit=100, db_url=db_url)
            matches = [b for b in builds if b.id.startswith(build_id)]
            if len(matches) == 1:
                build = matches[0]
            elif len(matches) > 1:
                typer.echo(
                    f"ERROR: ambiguous prefix {build_id!r} — {len(matches)} matches",
                    err=True,
                )
                raise typer.Exit(code=1)
            else:
                typer.echo(f"ERROR: build not found: {build_id!r}", err=True)
                raise typer.Exit(code=1)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    console = Console()
    try:
        dist_name, prof_name, board_name = _resolve_names(build, db_url)
    except Exception:
        dist_name = prof_name = board_name = "?"

    console.print(f"[bold]Build[/bold] {build.id}")
    console.print(f"  Target:    {dist_name}/{prof_name} → {board_name}")
    console.print(f"  Status:    {build.status}")
    console.print(f"  Hash:      {build.resolution_hash or '(none)'}")
    console.print(f"  Created:   {build.created_at}")
    console.print(f"  Updated:   {build.updated_at}")

    jobs = list_build_jobs(build.id, db_url=db_url)
    if jobs:
        tbl = Table("Job ID", "Step", "Status", title="Build Jobs")
        for j in jobs:
            if j.status == "success":
                color = "green"
            elif j.status == "failed":
                color = "red"
            else:
                color = "yellow"
            tbl.add_row(j.id[:8], j.step_kind, f"[{color}]{j.status}[/{color}]")
        console.print(tbl)

    # Optionally print BuildLog lines
    if show_logs:
        log_lines = get_build_logs(build.id, limit=log_limit, db_url=db_url)
        if log_lines:
            console.print(f"\n[bold]Log lines[/bold] (showing up to {log_limit}):")
            for ln in log_lines:
                ts_str = ln.ts.strftime("%H:%M:%S") if ln.ts else ""
                console.print(f"  [{ts_str}] {ln.message}")
        else:
            console.print("\n[dim]No log lines recorded.[/dim]")


@builds_app.command("logs")
def builds_logs(
    build_id: Annotated[str, typer.Argument(help="Build ID")],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Show build events for a build."""
    try:
        events = list_build_events(build_id, db_url=db_url)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    if not events:
        typer.echo("No events found for this build.")
        return

    for ev in events:
        ts = ev.ts.strftime("%H:%M:%S") if ev.ts else ""
        payload = str(ev.payload_json or {})
        typer.echo(f"[{ts}] {ev.event_type}  {payload}")
