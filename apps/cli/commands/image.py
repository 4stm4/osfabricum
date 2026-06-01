"""``osfabricumctl image`` subcommands (M17)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from osfabricum.image.composer import ImageSpec, compose_image

image_app = typer.Typer(help="Compose and inspect disk images", no_args_is_help=True)


@image_app.command("compose")
def image_compose(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board name")],
    arch: Annotated[str, typer.Option("--arch", help="Target architecture")],
    rootfs: Annotated[str, typer.Option("--rootfs", help="Composed rootfs artifact ID (M16)")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT"),
    ],
    kernel: Annotated[
        str | None,
        typer.Option("--kernel", help="Kernel artifact ID"),
    ] = None,
    firmware: Annotated[
        list[str],
        typer.Option("--firmware", "-f", help="Firmware artifact ID (repeatable)"),
    ] = [],  # noqa: B006
    dtb: Annotated[
        list[str],
        typer.Option("--dtb", "-d", help="DTB artifact ID (repeatable)"),
    ] = [],  # noqa: B006
    boot_mb: Annotated[
        int,
        typer.Option("--boot-mb", help="Boot partition size in MiB"),
    ] = 64,
    rootfs_mb: Annotated[
        int,
        typer.Option("--rootfs-mb", help="Rootfs partition size in MiB"),
    ] = 512,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Compose a bootable disk image from a rootfs artifact."""
    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo("ERROR: target must be <distribution>/<profile>", err=True)
        raise typer.Exit(code=1)
    distribution, profile = parts

    spec = ImageSpec(
        distribution=distribution,
        profile=profile,
        board=board,
        arch=arch,
        rootfs_artifact_id=rootfs,
        kernel_artifact_id=kernel,
        firmware_artifact_ids=list(firmware),
        dtb_artifact_ids=list(dtb),
        boot_size_mb=boot_mb,
        rootfs_size_mb=rootfs_mb,
    )

    console = Console()
    console.print(
        f"Composing image for [bold]{distribution}/{profile}[/bold] → [bold]{board}[/bold]"
    )

    result = compose_image(spec, store_root=store_root, db_url=db_url)

    for line in result.logs:
        console.print(f"  {line}")

    if not result.success:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] artifact: {result.artifact_id}")
    console.print(
        f"  size: {result.image_size_bytes / 1024 / 1024:.1f} MiB (compressed)"
    )
    if result.boot_files:
        console.print(f"  boot files: {', '.join(result.boot_files)}")
