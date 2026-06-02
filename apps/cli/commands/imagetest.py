"""``osfabricumctl test`` subcommands (M22)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from osfabricum.testkit.runner import run_image_test
from osfabricum.testkit.suites import get_suite, list_suites

test_app = typer.Typer(help="Run image tests", no_args_is_help=True)


@test_app.command("list-suites")
def test_list_suites() -> None:
    """List available built-in test suites."""
    tbl = Table("Suite", "Cases", "Description", title="Test Suites")
    for s in list_suites():
        tbl.add_row(s.name, str(len(s.cases)), s.description)
    Console().print(tbl)


@test_app.command("run")
def test_run(
    artifact_id: Annotated[str, typer.Argument(help="Image artifact ID to test")],
    suite: Annotated[str, typer.Option("--suite", help="Suite name (default: smoke)")] = "smoke",
    store_root: Annotated[
        Path,
        typer.Option("--store-root", envvar="OSFABRICUM_STORE_ROOT", help="Artifact store root"),
    ] = None,  # type: ignore[assignment]
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Boot timeout in seconds"),
    ] = 60,
    db_url: Annotated[
        str | None,
        typer.Option("--db-url", envvar="OSFABRICUM_DB_URL"),
    ] = None,
) -> None:
    """Run a test SUITE against an image artifact (boots it under QEMU)."""
    if store_root is None:
        typer.echo("ERROR: --store-root is required", err=True)
        raise typer.Exit(code=1)

    try:
        get_suite(suite)
    except KeyError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None

    console = Console()
    console.print(
        f"Running suite [bold]{suite}[/bold] against artifact "
        f"[bold]{artifact_id[:8]}…[/bold]"
    )

    result = run_image_test(
        artifact_id,
        suite,
        store_root=store_root,
        timeout_s=timeout,
        db_url=db_url,
    )

    for line in result.logs:
        console.print(f"  {line}")

    if result.error:
        typer.echo(f"ERROR: {result.error}", err=True)
        raise typer.Exit(code=1)

    # Per-case result table
    tbl = Table("Case", "Kind", "Result", title=f"Results — {suite}")
    for c in result.cases:
        color = {"pass": "green", "fail": "red", "skip": "yellow"}.get(c.outcome, "white")
        tbl.add_row(
            c.name, c.kind,
            f"[{color}]{c.outcome}[/{color}]" + (f" ({c.detail})" if c.detail else ""),
        )
    console.print(tbl)

    summary = f"{result.passed} passed, {result.failed} failed, {result.skipped} skipped"
    if result.success:
        console.print(f"[green]✓[/green] {summary}")
    else:
        console.print(f"[red]✗[/red] {summary}")
        raise typer.Exit(code=1)
