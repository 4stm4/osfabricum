"""M53 — Hardware probe import CLI."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import probe
from osfabricum.db.session import sync_session

app = typer.Typer(help="Hardware probe import designer (M53)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("source-list")
def source_list(ctx: typer.Context) -> None:
    """List probe source kinds."""
    with sync_session(_db(ctx)) as s:
        kinds = probe.list_probe_source_kinds(s)
    t = Table(title="Probe Source Kinds")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


@app.command("list")
def list_probes(ctx: typer.Context) -> None:
    """List all hardware probes."""
    with sync_session(_db(ctx)) as s:
        probes = probe.list_hardware_probes(s)
    t = Table(title="Hardware Probes")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Source")
    t.add_column("Arch")
    t.add_column("CPU")
    t.add_column("RAM (MB)")
    for p in probes:
        t.add_row(p.id, p.name, p.probe_source, p.cpu_arch or "—",
                  (p.cpu_model or "—")[:40], str(p.mem_mb) if p.mem_mb else "—")
    console.print(t)


@app.command("import")
def import_probe(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    probe_json: str = typer.Argument(..., help="JSON string or @file path"),
    probe_source: str = typer.Option("manual", "--source", "-s"),
    board_id: Optional[str] = typer.Option(None, "--board"),
) -> None:
    """Import a hardware probe record."""
    if probe_json.startswith("@"):
        from pathlib import Path  # noqa: PLC0415
        probe_data = json.loads(Path(probe_json[1:]).read_text())
    else:
        probe_data = json.loads(probe_json)
    with sync_session(_db(ctx)) as s:
        try:
            p = probe.import_hardware_probe(s, name, probe_data, probe_source, board_id)
            s.commit()
            console.print(f"[green]Imported[/green] probe [cyan]{p.id}[/cyan]  hash={p.content_hash}")
        except (ValueError, json.JSONDecodeError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("show")
def show_probe(ctx: typer.Context, probe_id: str) -> None:
    """Show hardware probe details."""
    with sync_session(_db(ctx)) as s:
        try:
            p = probe.get_hardware_probe(s, probe_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    console.rule(f"[cyan]{p.name}[/cyan]  ({p.id})")
    console.print(f"  source:    {p.probe_source}")
    console.print(f"  cpu_arch:  {p.cpu_arch or '—'}")
    console.print(f"  cpu_model: {p.cpu_model or '—'}")
    console.print(f"  mem_mb:    {p.mem_mb or '—'}")
    console.print(f"  hash:      {p.content_hash or '—'}")
    if p.rendered_board_hints:
        console.rule("Board Hints")
        console.print(p.rendered_board_hints)


@app.command("delete")
def delete_probe(ctx: typer.Context, probe_id: str) -> None:
    """Delete a hardware probe record."""
    with sync_session(_db(ctx)) as s:
        try:
            probe.delete_hardware_probe(s, probe_id)
            s.commit()
            console.print(f"[green]Deleted[/green] probe [cyan]{probe_id}[/cyan]")
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
