"""``osfabricumctl flash`` subcommands (M21)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from osfabricum.flasher.device import list_devices
from osfabricum.flasher.flash import flash_image_artifact

flash_app = typer.Typer(help="Flash images to devices", no_args_is_help=True)


@flash_app.command("list-devices")
def flash_list_devices() -> None:
    """List removable block devices detected on this host."""
    devices = list_devices()
    if not devices:
        typer.echo("No removable block devices detected (or unsupported platform).")
        return
    tbl = Table("Device", "Size", "Model", "Removable", title="Block Devices")
    for d in devices:
        tbl.add_row(d.path, d.human_size(), d.model or "—", "yes" if d.removable else "no")
    Console().print(tbl)


@flash_app.command("image")
def flash_image_cmd(
    artifact_id: Annotated[str, typer.Argument(help="Image artifact ID to flash")],
    device: Annotated[str, typer.Option("--device", help="Target device path")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Artifact store root"),
    ],
    allow: Annotated[
        list[str],
        typer.Option("--allow", help="Allowlist glob for device (repeatable, required)"),
    ] = [],  # noqa: B006
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate and report only; do not write"),
    ] = False,
    no_verify: Annotated[
        bool,
        typer.Option("--no-verify", help="Skip read-back verification"),
    ] = False,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Flash an image artifact to DEVICE (must be on the --allow list)."""
    if not allow:
        typer.echo(
            "ERROR: refusing to flash without an explicit --allow pattern "
            "(safety). Example: --allow '/dev/sdb'",
            err=True,
        )
        raise typer.Exit(code=1)

    console = Console()
    console.print(
        f"Flashing artifact [bold]{artifact_id[:8]}…[/bold] → [bold]{device}[/bold]"
        + (" [yellow](dry-run)[/yellow]" if dry_run else "")
    )

    result = flash_image_artifact(
        artifact_id,
        device,
        store_root=store_root,
        allowlist=tuple(allow),
        dry_run=dry_run,
        verify=not no_verify,
        db_url=db_url,
    )

    for line in result.logs:
        console.print(f"  {line}")

    if not result.success:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    if result.dry_run:
        console.print("[green]✓[/green] dry-run OK — device allowed, image ready")
    else:
        verified = "[green]verified[/green]" if result.verified else "[yellow]unverified[/yellow]"
        console.print(
            f"[green]✓[/green] flashed {result.bytes_written} bytes to {device} ({verified})"
        )


@flash_app.command("verify")
def flash_verify(
    artifact_id: Annotated[str, typer.Argument(help="Image artifact ID")],
    device: Annotated[str, typer.Option("--device", help="Device path to verify against")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT"),
    ],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Verify that DEVICE matches the image artifact (read-back compare)."""
    import gzip
    import hashlib

    from sqlalchemy import select

    from osfabricum.db.models import Artifact
    from osfabricum.db.session import sync_session
    from osfabricum.store.layout import blob_path

    console = Console()
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
        if art is None:
            typer.echo(f"ERROR: artifact not found: {artifact_id!r}", err=True)
            raise typer.Exit(code=1)
        sha256 = art.blob_sha256

    bp = blob_path(store_root, sha256)
    raw = bp.read_bytes()
    image_data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    expected = hashlib.sha256(image_data).hexdigest()

    try:
        h = hashlib.sha256()
        remaining = len(image_data)
        with open(device, "rb") as dev:  # noqa: PTH123
            while remaining > 0:
                chunk = dev.read(min(4 * 1024 * 1024, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
        actual = h.hexdigest()
    except OSError as exc:
        typer.echo(f"ERROR: cannot read device: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if actual == expected:
        console.print(f"[green]✓[/green] {device} matches artifact {artifact_id[:8]}…")
    else:
        console.print(
            f"[red]✗[/red] mismatch: expected {expected[:16]}…, got {actual[:16]}…"
        )
        raise typer.Exit(code=1)
