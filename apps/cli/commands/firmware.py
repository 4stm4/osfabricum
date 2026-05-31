"""``osfabricumctl firmware`` subcommands (M11)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Board, FirmwareBlob
from osfabricum.db.session import sync_session

firmware_app = typer.Typer(help="Manage firmware blobs", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


# ---------------------------------------------------------------------------
# firmware fetch
# ---------------------------------------------------------------------------


@firmware_app.command("fetch")
def firmware_fetch(
    board: Annotated[str, typer.Argument(help="Board name (e.g. rpi-zero-2w)")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Artifact store root"),
    ],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """Download all firmware blobs registered for BOARD."""
    from osfabricum.firmware.fetch import fetch_all_firmware

    try:
        blobs = fetch_all_firmware(board_name=board, store_root=store_root, db_url=db_url)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    typer.echo(f"Fetched {len(blobs)} firmware blob(s) for board '{board}'")


# ---------------------------------------------------------------------------
# firmware list
# ---------------------------------------------------------------------------


@firmware_app.command("list")
def firmware_list(
    board: Annotated[str | None, typer.Argument(help="Board name filter (optional)")] = None,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """List registered firmware blobs."""
    try:
        with sync_session(db_url) as session:
            query = select(FirmwareBlob)
            if board is not None:
                board_row = session.scalar(select(Board).where(Board.name == board))
                if board_row is None:
                    typer.echo(f"ERROR: board '{board}' not found", err=True)
                    raise typer.Exit(code=1)
                query = query.where(FirmwareBlob.board_id == board_row.id)
            blobs = session.scalars(query.order_by(FirmwareBlob.filename)).all()
            board_map = {b.id: b.name for b in session.scalars(select(Board)).all()}

        tbl = Table(
            "Board", "Filename", "Placement", "Required", "Artifact",
            title="Firmware Blobs",
        )
        for b in blobs:
            tbl.add_row(
                board_map.get(b.board_id, b.board_id),
                b.filename,
                b.placement,
                "yes" if b.required else "no",
                b.artifact_id or "(none)",
            )
        Console().print(tbl)
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# firmware import  (from catalog YAML — handled via catalog import)
# ---------------------------------------------------------------------------

# NOTE: bulk import of FirmwareList entries is handled by
#   ``catalog import --file firmware.yaml``
# The firmware_app does not duplicate that logic here.
