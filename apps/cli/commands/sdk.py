"""M50 — SDK / dev-shell export designer CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import sdk
from osfabricum.db.session import sync_session

app = typer.Typer(help="SDK / dev-shell export designer (M50)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("format-list")
def format_list(ctx: typer.Context) -> None:
    """List known SDK export formats."""
    with sync_session(_db(ctx)) as s:
        kinds = sdk.list_sdk_export_kinds(s)
    t = Table(title="SDK Export Formats")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


@app.command("list")
def list_profiles(
    ctx: typer.Context,
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
) -> None:
    """List SDK profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = sdk.list_sdk_profiles(s, distribution_id)
    t = Table(title="SDK Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Format")
    t.add_column("Python")
    t.add_column("Debug")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(
            p.id, p.name, p.export_format, p.python_version,
            "[green]yes[/green]" if p.include_debug_symbols else "no",
            (p.content_hash or "")[:16] + "…" if p.content_hash else "—",
        )
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    export_format: str = typer.Option("shell-env", "--format", "-f"),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
    python_version: str = typer.Option("3.11", "--python"),
    include_debug_symbols: bool = typer.Option(False, "--debug/--no-debug"),
) -> None:
    """Create a new SDK profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = sdk.create_sdk_profile(
                s, name, export_format, distribution_id, description,
                python_version, include_debug_symbols,
            )
            s.commit()
            console.print(f"[green]Created[/green] SDK profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("show")
def show_profile(ctx: typer.Context, profile_id: str) -> None:
    """Show an SDK profile and its variables."""
    with sync_session(_db(ctx)) as s:
        try:
            p = sdk.get_sdk_profile(s, profile_id)
            variables = sdk.list_sdk_variables(s, profile_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.rule(f"[cyan]{p.name}[/cyan]  ({p.id})")
    console.print(f"  format:   {p.export_format}")
    console.print(f"  python:   {p.python_version}")
    console.print(f"  debug:    {p.include_debug_symbols}")
    console.print(f"  hash:     {p.content_hash or '—'}")

    if variables:
        t = Table(title="SDK Variables")
        t.add_column("Key", style="cyan")
        t.add_column("Value")
        t.add_column("Secret?")
        t.add_column("Description")
        for v in variables:
            t.add_row(
                v.key,
                "****" if v.is_secret else v.value[:60],
                "[red]yes[/red]" if v.is_secret else "no",
                v.description[:60],
            )
        console.print(t)


@app.command("update")
def update_profile(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    export_format: Optional[str] = typer.Option(None, "--format"),
    python_version: Optional[str] = typer.Option(None, "--python"),
    description: Optional[str] = typer.Option(None, "--desc"),
    include_debug_symbols: Optional[bool] = typer.Option(None, "--debug/--no-debug"),
) -> None:
    """Update SDK profile settings."""
    updates: dict = {}
    if export_format is not None:
        updates["export_format"] = export_format
    if python_version is not None:
        updates["python_version"] = python_version
    if description is not None:
        updates["description"] = description
    if include_debug_symbols is not None:
        updates["include_debug_symbols"] = include_debug_symbols
    with sync_session(_db(ctx)) as s:
        try:
            sdk.update_sdk_profile(s, profile_id, **updates)
            s.commit()
            console.print(f"[green]Updated[/green] SDK profile [cyan]{profile_id}[/cyan]")
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("var-set")
def var_set(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    key: str = typer.Argument(...),
    value: str = typer.Argument(...),
    description: str = typer.Option("", "--desc"),
    is_secret: bool = typer.Option(False, "--secret/--no-secret"),
) -> None:
    """Set (upsert) a key/value variable in an SDK profile."""
    with sync_session(_db(ctx)) as s:
        try:
            v = sdk.set_sdk_variable(s, profile_id, key, value, description, is_secret)
            s.commit()
            console.print(
                f"[green]Set[/green] variable [cyan]{v.key}[/cyan] "
                f"in profile [cyan]{profile_id}[/cyan]"
            )
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show_setup: bool = typer.Option(False, "--setup", help="Print setup script"),
    show_env: bool = typer.Option(False, "--env", help="Print env script"),
) -> None:
    """Render SDK export scripts and store hash."""
    with sync_session(_db(ctx)) as s:
        try:
            p = sdk.render_sdk_export(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show_setup and p.rendered_setup_script:
        console.rule("Setup Script")
        console.print(p.rendered_setup_script)
    if show_env and p.rendered_env_script:
        console.rule("Env Script")
        console.print(p.rendered_env_script)
