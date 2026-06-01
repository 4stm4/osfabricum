"""``osfabricumctl compose`` subcommands (M16)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from osfabricum.composer.rootfs import RootfsComposeSpec, compose_rootfs

compose_app = typer.Typer(help="Compose rootfs and images", no_args_is_help=True)


@compose_app.command("rootfs")
def compose_rootfs_cmd(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board name")],
    arch: Annotated[str, typer.Option("--arch", help="Target architecture")],
    base: Annotated[str, typer.Option("--base", help="Base rootfs artifact ID (from M15)")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT"),
    ],
    packages: Annotated[
        list[str],
        typer.Option("--package", "-p", help="Package artifact ID (repeatable)"),
    ] = [],  # noqa: B006
    overlays: Annotated[
        list[str],
        typer.Option("--overlay", "-o", help="Overlay artifact ID (repeatable)"),
    ] = [],  # noqa: B006
    services: Annotated[
        list[str],
        typer.Option("--service", "-s", help="Service name to install (repeatable)"),
    ] = [],  # noqa: B006
    init_system: Annotated[
        str,
        typer.Option("--init-system", help="Init system: busybox | systemd"),
    ] = "busybox",
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Compose a rootfs: install packages, overlays, and services."""
    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo("ERROR: target must be <distribution>/<profile>", err=True)
        raise typer.Exit(code=1)
    distribution, profile = parts

    spec = RootfsComposeSpec(
        distribution=distribution,
        profile=profile,
        board=board,
        arch=arch,
        base_artifact_id=base,
        package_artifact_ids=list(packages),
        overlay_artifact_ids=list(overlays),
        service_names=list(services),
        init_system=init_system,
    )

    console = Console()
    console.print(
        f"Composing rootfs for [bold]{distribution}/{profile}[/bold] → [bold]{board}[/bold]"
    )

    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)

    for line in result.logs:
        console.print(f"  {line}")

    if not result.success:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] artifact: {result.artifact_id}")
    if result.installed_packages:
        console.print(f"  packages: {', '.join(result.installed_packages)}")
    if result.installed_services:
        console.print(f"  services: {', '.join(result.installed_services)}")
