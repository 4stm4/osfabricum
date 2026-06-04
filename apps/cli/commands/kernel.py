"""Real implementations of ``osfabricumctl kernel`` subcommands (M10)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Architecture, Artifact, Kernel, KernelConfig
from osfabricum.db.session import sync_session
from osfabricum.kernel.build import build_kernel

kernel_app = typer.Typer(help="Build and inspect kernels", no_args_is_help=True)

console = Console()

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


# ---------------------------------------------------------------------------
# kernel build
# ---------------------------------------------------------------------------


@kernel_app.command("build")
def kernel_build(
    name: Annotated[str, typer.Argument(help="Kernel name (e.g. linux-rpi)")],
    board: Annotated[
        str | None,
        typer.Option("--board", "-b", help="Target board name"),
    ] = None,
    store: Annotated[
        Path,
        typer.Option("--store", help="Artifact store root"),
    ] = Path("store"),
    toolchain_root: Annotated[
        Path | None,
        typer.Option("--toolchain-root", help="Cross-compile toolchain prefix"),
    ] = None,
    src_dir: Annotated[
        Path | None,
        typer.Option(
            "--src-dir",
            help="Pre-extracted source directory (skip network fetch)",
            exists=False,
        ),
    ] = None,
    jobs: Annotated[int, typer.Option("--jobs", "-j", help="Parallel make jobs")] = 1,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """Cross-compile a kernel and store outputs as artifacts."""
    try:
        typer.echo(f"Building kernel {name!r}…")
        result = build_kernel(
            name,
            store_root=store,
            board_name=board,
            toolchain_root=toolchain_root,
            src_dir=src_dir,
            db_url=db_url,
            jobs=jobs,
        )
    except OperationalError:
        console.print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None
    except Exception as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not result.success:
        typer.secho(f"FAILED: {result.error}", fg=typer.colors.RED, err=True)
        if result.work_dir:
            typer.secho(f"Work directory preserved: {result.work_dir}", err=True)
        raise typer.Exit(code=1)

    prefix = "cache-hit" if result.cache_hit else "built"
    typer.secho(f"OK ({prefix})", fg=typer.colors.GREEN)
    typer.echo(f"  image:   {result.image_artifact_id}")
    typer.echo(f"  modules: {result.modules_artifact_id}")
    for dtb_id in result.dtb_artifact_ids:
        typer.echo(f"  dtb:     {dtb_id}")


# ---------------------------------------------------------------------------
# kernel list
# ---------------------------------------------------------------------------


@kernel_app.command("list")
def kernel_list(
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """List registered kernels."""
    try:
        with sync_session(db_url) as session:
            rows = session.scalars(select(Kernel).order_by(Kernel.name)).all()
            arch_map = {a.id: a.name for a in session.scalars(select(Architecture)).all()}
    except OperationalError:
        console.print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    tbl = Table("Name", "Version", "Arch", "Source URI", title="Kernels")
    for k in rows:
        tbl.add_row(
            k.name,
            k.version,
            arch_map.get(k.arch_id, k.arch_id),
            k.source_uri or "",
        )
    console.print(tbl)


# ---------------------------------------------------------------------------
# kernel show
# ---------------------------------------------------------------------------


@kernel_app.command("show")
def kernel_show(
    name: Annotated[str, typer.Argument(help="Kernel name")],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
) -> None:
    """Show details for a single kernel, including cached artifacts."""
    try:
        with sync_session(db_url) as session:
            kernel = session.scalar(select(Kernel).where(Kernel.name == name))
            if kernel is None:
                typer.secho(f"ERROR: kernel {name!r} not found", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            arch_row = session.scalar(select(Architecture).where(Architecture.id == kernel.arch_id))
            arch_name = arch_row.name if arch_row else kernel.arch_id
            kc_rows = session.scalars(
                select(KernelConfig).where(KernelConfig.kernel_id == kernel.id)
            ).all()
            artifact_ids = [kc.config_artifact_id for kc in kc_rows if kc.config_artifact_id]
            artifacts = (
                session.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all()
                if artifact_ids
                else []
            )
    except OperationalError:
        console.print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    tbl = Table("Field", "Value", title=f"Kernel: {name}")
    tbl.add_row("id", kernel.id)
    tbl.add_row("name", kernel.name)
    tbl.add_row("version", kernel.version)
    tbl.add_row("arch", arch_name)
    tbl.add_row("source_uri", kernel.source_uri or "")
    tbl.add_row("source_ref", kernel.source_ref or "")
    console.print(tbl)

    if artifacts:
        art_tbl = Table("Artifact ID", "Kind", "Name", title="Cached artifacts")
        for art in artifacts:
            art_tbl.add_row(art.id, art.kind, art.name)
        console.print(art_tbl)
