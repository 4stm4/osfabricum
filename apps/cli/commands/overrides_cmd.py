"""M55 — Override / Masking engine CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import overrides
from osfabricum.db.session import sync_session

app = typer.Typer(help="Override / Masking engine (M55)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("action-list")
def action_list(ctx: typer.Context) -> None:
    """List override action kinds."""
    with sync_session(_db(ctx)) as s:
        kinds = overrides.list_override_kinds(s)
    t = Table(title="Override Action Kinds")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


@app.command("list")
def list_profiles(ctx: typer.Context, distribution_id: Optional[str] = typer.Option(None, "--dist")) -> None:
    """List override profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = overrides.list_override_profiles(s, distribution_id)
    t = Table(title="Override Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(p.id, p.name, (p.content_hash or "")[:16] + "…" if p.content_hash else "—")
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
) -> None:
    """Create an override profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = overrides.create_override_profile(s, name, distribution_id, description)
            s.commit()
            console.print(f"[green]Created[/green] override profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("rule-add")
def rule_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    target_type: str = typer.Argument(..., help="package|config|kernel-param|service|sysctl"),
    target_key: str = typer.Argument(...),
    action: str = typer.Argument(..., help="set|unset|mask|append|prepend|replace"),
    value: Optional[str] = typer.Option(None, "--value", "-v"),
    reason: str = typer.Option("", "--reason"),
    priority: int = typer.Option(0, "--priority"),
) -> None:
    """Add or update an override rule."""
    with sync_session(_db(ctx)) as s:
        try:
            r = overrides.add_override_rule(
                s, profile_id, target_type, target_key,
                action, value, reason, priority,
            )
            s.commit()
            console.print(
                f"[green]Set[/green] rule [cyan]{r.target_type}:{r.target_key}[/cyan] → [yellow]{r.action}[/yellow]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("rules")
def list_rules(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    target_type: Optional[str] = typer.Option(None, "--type"),
) -> None:
    """List override rules for a profile."""
    with sync_session(_db(ctx)) as s:
        try:
            rules = overrides.list_override_rules(s, profile_id, target_type)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    t = Table(title=f"Override Rules — {profile_id}")
    t.add_column("Type", style="cyan")
    t.add_column("Key")
    t.add_column("Action")
    t.add_column("Value")
    t.add_column("Priority")
    for r in rules:
        t.add_row(r.target_type, r.target_key[:60], r.action,
                  (r.value or "")[:40], str(r.priority))
    console.print(t)


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show: bool = typer.Option(False, "--show"),
) -> None:
    """Render override policy."""
    with sync_session(_db(ctx)) as s:
        try:
            p = overrides.render_override_policy(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc
    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show and p.rendered_override_policy:
        console.rule("Override Policy")
        console.print(p.rendered_override_policy)
