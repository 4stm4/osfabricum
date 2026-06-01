"""``osfabricumctl rootfs`` subcommands (M15)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from osfabricum.rootfs.builder import RootfsSpec, build_base_rootfs

rootfs_app = typer.Typer(help="RootFS operations", no_args_is_help=True)

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


@rootfs_app.command("init")
def rootfs_init(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board name")],
    arch: Annotated[str, typer.Option("--arch", help="Target architecture (e.g. aarch64)")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Artifact store root"),
    ],
    init_system: Annotated[
        str,
        typer.Option("--init-system", help="Init system: busybox | systemd"),
    ] = "busybox",
    hostname: Annotated[
        str,
        typer.Option("--hostname", help="Default hostname"),
    ] = "osfabricum",
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """Build a minimal base rootfs for DISTRIBUTION/PROFILE on BOARD."""
    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo("ERROR: target must be <distribution>/<profile>", err=True)
        raise typer.Exit(code=1)
    distribution, profile = parts

    spec = RootfsSpec(
        arch=arch,
        distribution=distribution,
        profile=profile,
        board=board,
        init_system=init_system,
        hostname=hostname,
    )

    console = Console()
    console.print(
        f"Building base rootfs for [bold]{distribution}/{profile}[/bold] "
        f"→ [bold]{board}[/bold] ({arch}), init=[cyan]{init_system}[/cyan]"
    )

    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)

    for line in result.logs:
        console.print(f"  {line}")

    if not result.success:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] artifact: {result.artifact_id}")
