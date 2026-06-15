"""M56 — Patch Queue / Source Patch Manager CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import patches
from osfabricum.db.session import sync_session

app = typer.Typer(help="Patch Queue / Source Patch Manager (M56)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("target-list")
def target_list(ctx: typer.Context) -> None:
    """List patch target kinds."""
    with sync_session(_db(ctx)) as s:
        kinds = patches.list_patch_target_kinds(s)
    t = Table(title="Patch Target Kinds")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


@app.command("list")
def list_sets(
    ctx: typer.Context,
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
) -> None:
    """List patch sets."""
    with sync_session(_db(ctx)) as s:
        pss = patches.list_patch_sets(s, distribution_id)
    t = Table(title="Patch Sets")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Target", style="yellow")
    t.add_column("Hash", style="dim")
    for ps in pss:
        h = (ps.content_hash or "")[:16] + "…" if ps.content_hash else "—"
        t.add_row(ps.id, ps.name, ps.target_kind, h)
    console.print(t)


@app.command("create")
def create_set(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    target_kind: str = typer.Option("kernel", "--target"),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
) -> None:
    """Create a patch set."""
    with sync_session(_db(ctx)) as s:
        try:
            ps = patches.create_patch_set(
                s, name, distribution_id, description, target_kind
            )
            s.commit()
            console.print(f"[green]Created[/green] patch set [cyan]{ps.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("patch-add")
def patch_add(
    ctx: typer.Context,
    patch_set_id: str = typer.Argument(...),
    sequence_num: int = typer.Argument(...),
    name: str = typer.Argument(...),
    content_file: Optional[Path] = typer.Option(None, "--file", "-f",
                                                  help="Read patch content from file"),
    patch_format: str = typer.Option("diff", "--format"),
    enabled: bool = typer.Option(True, "--enabled/--disabled"),
    description: str = typer.Option("", "--desc"),
) -> None:
    """Add or update a patch in a set."""
    content = ""
    if content_file:
        content = content_file.read_text()
    with sync_session(_db(ctx)) as s:
        try:
            p = patches.add_patch(
                s, patch_set_id, sequence_num, name,
                patch_content=content,
                patch_format=patch_format,
                is_enabled=enabled,
                description=description,
            )
            s.commit()
            console.print(
                f"[green]Set[/green] patch [cyan]seq={p.sequence_num}[/cyan] "
                f"[yellow]{p.name}[/yellow]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("patches")
def list_patches_cmd(
    ctx: typer.Context,
    patch_set_id: str = typer.Argument(...),
) -> None:
    """List patches in a set."""
    with sync_session(_db(ctx)) as s:
        try:
            all_patches = patches.list_patches(s, patch_set_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    t = Table(title=f"Patches — {patch_set_id}")
    t.add_column("Seq", style="cyan")
    t.add_column("Name")
    t.add_column("Format")
    t.add_column("Enabled")
    for p in all_patches:
        t.add_row(
            str(p.sequence_num), p.name[:60], p.patch_format,
            "[green]yes[/green]" if p.is_enabled else "[dim]no[/dim]",
        )
    console.print(t)


@app.command("render")
def render(
    ctx: typer.Context,
    patch_set_id: str = typer.Argument(...),
    show: bool = typer.Option(False, "--show"),
) -> None:
    """Render patch manifest."""
    with sync_session(_db(ctx)) as s:
        try:
            ps = patches.render_patch_manifest(s, patch_set_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    console.print(f"[green]Rendered[/green] {ps.content_hash}")
    if show and ps.rendered_patch_manifest:
        console.rule("Patch Manifest")
        console.print(ps.rendered_patch_manifest)


@app.command("apply")
def apply_cmd(
    ctx: typer.Context,
    patch_set_id: str = typer.Argument(...),
    status: str = typer.Option("success", "--status"),
    applied_count: int = typer.Option(0, "--count"),
    failed_seq: Optional[int] = typer.Option(None, "--failed-seq"),
    error: Optional[str] = typer.Option(None, "--error"),
) -> None:
    """Record a patch application result."""
    with sync_session(_db(ctx)) as s:
        try:
            r = patches.record_application(
                s, patch_set_id,
                status=status,
                applied_count=applied_count,
                failed_at_sequence=failed_seq,
                error_message=error,
            )
            s.commit()
            console.print(
                f"[green]Recorded[/green] apply result [cyan]{r.id}[/cyan] "
                f"— status=[yellow]{r.status}[/yellow] applied={r.applied_count}"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc
