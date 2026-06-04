"""``osfabricumctl`` — the OSFabricum operator CLI.

M1 registers the full top-level command surface from ROADMAP section 20 so
``--help`` is complete. Individual commands are stubs that report they are not
implemented yet; they gain behaviour in their respective milestones.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from apps.cli.commands.artifacts import artifacts_app
from apps.cli.commands.board import board_app
from apps.cli.commands.builds import builds_app
from apps.cli.commands.catalog import catalog_app
from apps.cli.commands.compose import compose_app
from apps.cli.commands.distribution import distribution_app
from apps.cli.commands.firmware import firmware_app
from apps.cli.commands.flash import flash_app
from apps.cli.commands.image import image_app
from apps.cli.commands.imagetest import test_app
from apps.cli.commands.kernel import kernel_app
from apps.cli.commands.package import package_app
from apps.cli.commands.plan import run_plan
from apps.cli.commands.profile import profile_app
from apps.cli.commands.rootfs import rootfs_app
from apps.cli.commands.source import source_app
from apps.cli.commands.store import store_app
from apps.cli.commands.toolchain import toolchain_app
from apps.cli.commands.workers import workers_app
from osfabricum import __version__

# group name -> (help text, subcommand names)
GROUPS: dict[str, tuple[str, list[str]]] = {
    # "builds" is registered as a real app below (M18)
    # "package" is registered as a real app below (M9)
    # "kernel" is registered as a real app below (M10)
    # "firmware" is registered as a real app below (M11)
    # "toolchain" is registered as a real app below (M6)
    "cache": ("Build cache maintenance", ["stats", "verify", "gc"]),
    # "flash" is registered as a real app below (M21)
    # "test" is registered as a real app below (M22)
    "releases": ("Manage releases and promotion", ["list", "show", "promote", "publish"]),
}


def _not_implemented(path: str) -> None:
    typer.secho(f"`osfabricumctl {path}` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


def _make_stub(path: str) -> Callable[[], None]:
    def _stub() -> None:
        _not_implemented(path)

    return _stub


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"osfabricumctl {__version__}")
        raise typer.Exit()


app = typer.Typer(
    help="osfabricumctl — OSFabricum operator CLI",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version and exit"
        ),
    ] = False,
) -> None:
    """OSFabricum operator CLI."""


@app.command()
def build(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board name")],
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Artifact store root"),
    ],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
    skip_image: Annotated[
        bool,
        typer.Option("--skip-image", help="Stop after rootfs.compose"),
    ] = False,
    init_system: Annotated[
        str,
        typer.Option("--init-system", help="Init system: busybox | systemd"),
    ] = "busybox",
    jobs: Annotated[
        int,
        typer.Option("--jobs", "-j", help="Parallel make jobs for kernel build"),
    ] = 1,
) -> None:
    """Start a full build pipeline (plan → rootfs → image)."""

    from rich.console import Console as _Console  # noqa: PLC0415

    from osfabricum.pipeline.coordinator import PipelineSpec, run_pipeline  # noqa: PLC0415

    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo("ERROR: target must be <distribution>/<profile>", err=True)
        raise typer.Exit(code=1)
    distribution, profile = parts

    spec = PipelineSpec(
        distribution=distribution,
        profile=profile,
        board=board,
        store_root=store_root,
        db_url=db_url,
        skip_image=skip_image,
        init_system=init_system,
        jobs=jobs,
    )

    console = _Console()
    console.print(f"Building [bold]{distribution}/{profile}[/bold] → [bold]{board}[/bold]")

    result = run_pipeline(spec)

    for line in result.logs:
        console.print(f"  {line}")

    if not result.success:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] build_id: {result.build_id or '(no DB)'}")
    if result.image_artifact_id:
        console.print(f"  image:   {result.image_artifact_id}")
    if result.rootfs_artifact_id:
        console.print(f"  rootfs:  {result.rootfs_artifact_id}")


@app.command()
def plan(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board name")],
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help="Output format: table | json"),
    ] = "table",
) -> None:
    """Resolve and display a build plan without building."""
    run_plan(target, board, db_url, output)  # M12


@app.command()
def prefetch(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
    ] = None,
) -> None:
    """Report sources / toolchains / packages a build plan would need (M29)."""
    from rich.console import Console as _Console  # noqa: PLC0415

    from osfabricum import orchestrator  # noqa: PLC0415

    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo("ERROR: target must be <distribution>/<profile>", err=True)
        raise typer.Exit(code=1)
    distribution, profile = parts
    try:
        report = orchestrator.prefetch_report(
            distribution=distribution, profile=profile, board=board, db_url=db_url
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None

    console = _Console()
    console.print(f"[bold]prefetch {distribution}/{profile} → {board}[/bold]")
    console.print(f"  toolchain: {report['toolchain'] or '—'}")
    console.print(f"  kernel:    {report['kernel'] or '—'}")
    for job in report["fetch_jobs"]:
        console.print(f"  • {job}")
    if not report["fetch_jobs"]:
        console.print("  [green]nothing to fetch[/green]")


def _register_groups() -> None:
    for name, (help_text, commands) in GROUPS.items():
        group = typer.Typer(help=help_text, no_args_is_help=True)
        for cmd in commands:
            group.command(name=cmd)(_make_stub(f"{name} {cmd}"))
        app.add_typer(group, name=name)
    app.add_typer(builds_app, name="builds")
    app.add_typer(catalog_app, name="catalog")
    app.add_typer(distribution_app, name="distribution")
    app.add_typer(profile_app, name="profile")
    app.add_typer(compose_app, name="compose")
    app.add_typer(image_app, name="image")
    app.add_typer(flash_app, name="flash")
    app.add_typer(test_app, name="test")
    app.add_typer(artifacts_app, name="artifacts")
    app.add_typer(firmware_app, name="firmware")
    app.add_typer(kernel_app, name="kernel")
    app.add_typer(rootfs_app, name="rootfs")
    app.add_typer(package_app, name="package")
    app.add_typer(source_app, name="source")
    app.add_typer(store_app, name="store")
    app.add_typer(toolchain_app, name="toolchain")
    app.add_typer(workers_app, name="workers")
    app.add_typer(board_app, name="board")


_register_groups()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
