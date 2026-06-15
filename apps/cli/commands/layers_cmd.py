"""M54 — OS Composition Layers designer CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import layers
from osfabricum.db.session import sync_session

app = typer.Typer(help="OS Composition Layers designer (M54)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("kind-list")
def kind_list(ctx: typer.Context) -> None:
    """List layer kinds."""
    with sync_session(_db(ctx)) as s:
        kinds = layers.list_layer_kinds(s)
    t = Table(title="Layer Kinds")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


@app.command("list")
def list_profiles(ctx: typer.Context, distribution_id: Optional[str] = typer.Option(None, "--dist")) -> None:
    """List layer profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = layers.list_layer_profiles(s, distribution_id)
    t = Table(title="Layer Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Base Layer")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(p.id, p.name, p.base_layer,
                  (p.content_hash or "")[:16] + "…" if p.content_hash else "—")
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    base_layer: str = typer.Option("base", "--base"),
    description: str = typer.Option("", "--desc"),
) -> None:
    """Create a layer profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = layers.create_layer_profile(s, name, distribution_id, description, base_layer)
            s.commit()
            console.print(f"[green]Created[/green] layer profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("entry-add")
def entry_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    name: str = typer.Argument(...),
    layer_kind: str = typer.Argument(..., help="base|bsp|extension|app|compliance|debug"),
    source_url: Optional[str] = typer.Option(None, "--url"),
    sha256_hint: Optional[str] = typer.Option(None, "--sha256"),
    priority: int = typer.Option(0, "--priority"),
    is_enabled: bool = typer.Option(True, "--enabled/--disabled"),
    description: str = typer.Option("", "--desc"),
) -> None:
    """Add or update a layer entry."""
    with sync_session(_db(ctx)) as s:
        try:
            e = layers.add_layer_entry(
                s, profile_id, name, layer_kind,
                source_url, sha256_hint, priority, is_enabled, description,
            )
            s.commit()
            console.print(f"[green]Set[/green] layer entry [cyan]{e.name}[/cyan] [{e.layer_kind}]")
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show: bool = typer.Option(False, "--show"),
) -> None:
    """Render layer manifest."""
    with sync_session(_db(ctx)) as s:
        try:
            p = layers.render_layer_manifest(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show and p.rendered_manifest:
        console.rule("Layer Manifest")
        console.print(p.rendered_manifest)
