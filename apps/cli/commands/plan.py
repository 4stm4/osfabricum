"""``osfabricumctl plan`` command (M12).

Resolves and displays a build plan for a distribution/profile/board triple
without starting any actual build.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy.exc import OperationalError

from osfabricum.resolver import resolve_plan

_DB_NOT_READY = (
    "[red]Error:[/red] database schema not found.\nRun [bold]alembic upgrade head[/bold] first."
)


def run_plan(
    target: str,
    board: str,
    db_url: str | None,
    output_format: str,
) -> None:
    """Resolve and print a build plan.  Extracted for testability."""
    parts = target.split("/", 1)
    if len(parts) != 2 or not all(parts):
        typer.echo(
            "ERROR: target must be in the form <distribution>/<profile>",
            err=True,
        )
        raise typer.Exit(code=1)
    distribution, profile = parts

    try:
        plan = resolve_plan(distribution, profile, board, db_url=db_url)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except OperationalError:
        Console().print(_DB_NOT_READY)
        raise typer.Exit(code=1) from None

    if output_format == "json":
        typer.echo(json.dumps(plan.to_dict(), indent=2))
        return

    # ---- rich table output ----
    console = Console()

    console.print(
        Panel(
            f"[bold]{plan.distribution}[/bold] / {plan.profile}  "
            f"→  [bold]{plan.board}[/bold] ([cyan]{plan.arch}[/cyan])\n"
            f"resolution_hash: [dim]{plan.resolution_hash}[/dim]",
            title="Build Plan",
            expand=False,
        )
    )

    # Toolchain
    if plan.toolchain:
        tc = plan.toolchain
        status = "[green]✓[/green]" if tc.artifact_id else "[yellow]missing[/yellow]"
        console.print(
            f"  Toolchain: {tc.name} {tc.version}  {status}"
        )
    else:
        console.print("  Toolchain: [yellow]none[/yellow]")

    # Kernel
    if plan.kernel:
        k = plan.kernel
        status = "[green]✓[/green]" if k.artifact_id else "[yellow]missing[/yellow]"
        console.print(f"  Kernel:    {k.name} {k.version}  {status}")
    else:
        console.print("  Kernel:    [yellow]none[/yellow]")

    # Packages
    if plan.packages:
        tbl = Table("Package", "Version", "Arch", "Status", title="Packages")
        for pkg in sorted(plan.packages, key=lambda p: p.name):
            color = "green" if pkg.artifact_id else "yellow"
            tbl.add_row(
                pkg.name, pkg.version, pkg.arch,
                f"[{color}]{pkg.status}[/{color}]",
            )
        console.print(tbl)

    # Firmware
    if plan.firmware:
        tbl = Table("Filename", "Placement", "Required", "Status", title="Firmware")
        for fw in plan.firmware:
            ok = "[green]✓[/green]" if fw.artifact_id else "[yellow]missing[/yellow]"
            tbl.add_row(fw.filename, fw.placement, "yes" if fw.required else "no", ok)
        console.print(tbl)

    # Missing / required jobs
    if plan.missing_artifacts:
        console.print(
            Panel(
                "\n".join(f"  • {m}" for m in plan.missing_artifacts),
                title="[yellow]Missing artifacts[/yellow]",
                expand=False,
            )
        )
    if plan.required_jobs:
        console.print(
            Panel(
                "\n".join(f"  {i+1}. {j}" for i, j in enumerate(plan.required_jobs)),
                title="Required jobs",
                expand=False,
            )
        )


def make_plan_command() -> typer.main.CommandInfo:
    """Return the ``plan`` command bound to :func:`run_plan`."""

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
        run_plan(target, board, db_url, output)

    return plan  # type: ignore[return-value]
