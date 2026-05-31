"""Real implementations of ``osfabricumctl workers`` subcommands (M4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Worker
from osfabricum.db.session import sync_session

workers_app = typer.Typer(help="Inspect worker inventory", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)

_STALE_THRESHOLD_S = 180  # 3 × default lease_ttl_s=60


def _status(worker: Worker) -> str:
    if not worker.enabled:
        return "disabled"
    if worker.last_seen_at is None:
        return "unknown"
    age = (datetime.now(UTC).replace(tzinfo=None) - worker.last_seen_at).total_seconds()
    return "online" if age <= _STALE_THRESHOLD_S else "stale"


@workers_app.command("list")
def workers_list(
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """List registered workers and their status."""
    try:
        with sync_session(db_url) as session:
            rows = session.scalars(select(Worker).order_by(Worker.hostname)).all()
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    tbl = Table("Hostname", "Status", "Kinds", "Tags", "Capabilities", "Last seen", title="Workers")
    for w in rows:
        kinds = ", ".join(w.kinds_json or []) or "-"
        tags = ", ".join(w.tags_json or []) or "-"
        seen = w.last_seen_at.isoformat(timespec="seconds") if w.last_seen_at else "-"
        caps_raw = w.capabilities_json or {}
        caps = ", ".join(f"{k}={v}" for k, v in caps_raw.items()) if caps_raw else "-"
        tbl.add_row(w.hostname, _status(w), kinds, tags, caps, seen)
    Console().print(tbl)


@workers_app.command("show")
def workers_show(
    hostname: Annotated[str, typer.Argument(help="Worker hostname")],
) -> None:
    """Show details for a single worker."""
    typer.secho("`workers show` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@workers_app.command("disable")
def workers_disable(
    hostname: Annotated[str, typer.Argument(help="Worker hostname")],
) -> None:
    """Disable a worker (stops it from claiming new jobs)."""
    typer.secho("`workers disable` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@workers_app.command("enable")
def workers_enable(
    hostname: Annotated[str, typer.Argument(help="Worker hostname")],
) -> None:
    """Re-enable a previously disabled worker."""
    typer.secho("`workers enable` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
