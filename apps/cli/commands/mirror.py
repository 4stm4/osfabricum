"""M51 — Cache / Mirror / Offline designer CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import mirror
from osfabricum.db.session import sync_session

app = typer.Typer(help="Cache / Mirror / Offline designer (M51)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


@app.command("policy-list")
def policy_list(ctx: typer.Context) -> None:
    """List cache policy kinds."""
    with sync_session(_db(ctx)) as s:
        kinds = mirror.list_cache_policy_kinds(s)
    t = Table(title="Cache Policy Kinds")
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
    """List mirror profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = mirror.list_mirror_profiles(s, distribution_id)
    t = Table(title="Mirror Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Offline?")
    t.add_column("TTL (days)")
    t.add_column("Max cache (MB)")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(
            p.id, p.name,
            "[red]YES[/red]" if p.offline_mode else "no",
            str(p.cache_ttl_days),
            str(p.max_cache_size_mb) if p.max_cache_size_mb else "—",
            (p.content_hash or "")[:16] + "…" if p.content_hash else "—",
        )
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
    offline_mode: bool = typer.Option(False, "--offline/--online"),
    max_cache_size_mb: Optional[int] = typer.Option(None, "--max-size-mb"),
    cache_ttl_days: int = typer.Option(7, "--ttl-days"),
) -> None:
    """Create a new mirror profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = mirror.create_mirror_profile(
                s, name, distribution_id, description,
                offline_mode, max_cache_size_mb, cache_ttl_days,
            )
            s.commit()
            console.print(f"[green]Created[/green] mirror profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("show")
def show_profile(ctx: typer.Context, profile_id: str) -> None:
    """Show a mirror profile with endpoints and cache rules."""
    with sync_session(_db(ctx)) as s:
        try:
            p = mirror.get_mirror_profile(s, profile_id)
            endpoints = mirror.list_mirror_endpoints(s, profile_id)
            rules = mirror.list_cache_rules(s, profile_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.rule(f"[cyan]{p.name}[/cyan]  ({p.id})")
    console.print(f"  offline_mode:    {p.offline_mode}")
    console.print(f"  cache_ttl_days:  {p.cache_ttl_days}")
    if p.max_cache_size_mb:
        console.print(f"  max_cache_size:  {p.max_cache_size_mb} MB")
    console.print(f"  content_hash:    {p.content_hash or '—'}")

    if endpoints:
        t = Table(title="Mirror Endpoints")
        t.add_column("Priority")
        t.add_column("URL", style="cyan")
        t.add_column("Default?")
        t.add_column("Auth?")
        for ep in endpoints:
            t.add_row(
                str(ep.priority), ep.url,
                "[green]yes[/green]" if ep.is_default else "no",
                "[yellow]yes[/yellow]" if ep.requires_auth else "no",
            )
        console.print(t)

    if rules:
        t = Table(title="Cache Rules")
        t.add_column("Priority")
        t.add_column("Pattern", style="cyan")
        t.add_column("Policy")
        for r in rules:
            t.add_row(str(r.priority), r.source_pattern, r.cache_policy)
        console.print(t)


@app.command("update")
def update_profile(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    offline_mode: Optional[bool] = typer.Option(None, "--offline/--online"),
    cache_ttl_days: Optional[int] = typer.Option(None, "--ttl-days"),
    description: Optional[str] = typer.Option(None, "--desc"),
) -> None:
    """Update mirror profile settings."""
    updates: dict = {}
    if offline_mode is not None:
        updates["offline_mode"] = offline_mode
    if cache_ttl_days is not None:
        updates["cache_ttl_days"] = cache_ttl_days
    if description is not None:
        updates["description"] = description
    with sync_session(_db(ctx)) as s:
        try:
            mirror.update_mirror_profile(s, profile_id, **updates)
            s.commit()
            console.print(f"[green]Updated[/green] mirror profile [cyan]{profile_id}[/cyan]")
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("endpoint-add")
def endpoint_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    url: str = typer.Argument(...),
    priority: int = typer.Option(0, "--priority"),
    is_default: bool = typer.Option(False, "--default/--no-default"),
    requires_auth: bool = typer.Option(False, "--auth/--no-auth"),
    auth_token_id: Optional[str] = typer.Option(None, "--token-id"),
) -> None:
    """Add or update a mirror endpoint."""
    with sync_session(_db(ctx)) as s:
        try:
            ep = mirror.add_mirror_endpoint(
                s, profile_id, url, priority, is_default, requires_auth, auth_token_id
            )
            s.commit()
            console.print(
                f"[green]Set[/green] endpoint [cyan]{ep.url}[/cyan] "
                f"in profile [cyan]{profile_id}[/cyan]"
            )
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("rule-add")
def rule_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    source_pattern: str = typer.Argument(...),
    cache_policy: str = typer.Argument(..., help="always | prefer | bypass | offline-only"),
    priority: int = typer.Option(0, "--priority"),
) -> None:
    """Add or update a cache priority rule."""
    with sync_session(_db(ctx)) as s:
        try:
            r = mirror.add_cache_rule(
                s, profile_id, source_pattern, cache_policy, priority
            )
            s.commit()
            console.print(
                f"[green]Set[/green] rule [cyan]{r.source_pattern}[/cyan] → "
                f"[yellow]{r.cache_policy}[/yellow] in profile [cyan]{profile_id}[/cyan]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show_config: bool = typer.Option(False, "--config", help="Print mirror config"),
) -> None:
    """Render mirror configuration and store hash."""
    with sync_session(_db(ctx)) as s:
        try:
            p = mirror.render_mirror_config(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show_config and p.rendered_mirror_config:
        console.rule("Mirror Config")
        console.print(p.rendered_mirror_config)
