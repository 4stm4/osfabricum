"""M49 — Update / OTA / Recovery Designer CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import updates as upd
from osfabricum.db.session import sync_session

app = typer.Typer(help="Update / OTA / Recovery Designer (M49)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Strategy kinds
# ---------------------------------------------------------------------------


@app.command("strategy-list")
def strategy_list(ctx: typer.Context) -> None:
    """List known update strategies."""
    with sync_session(_db(ctx)) as s:
        kinds = upd.list_update_strategy_kinds(s)
    t = Table(title="Update Strategy Kinds")
    t.add_column("Kind", style="cyan")
    t.add_column("Label")
    t.add_column("Description")
    for k in kinds:
        t.add_row(k.kind, k.label, k.description[:80])
    console.print(t)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@app.command("list")
def list_profiles(
    ctx: typer.Context,
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
) -> None:
    """List update profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = upd.list_update_profiles(s, distribution_id)
    t = Table(title="Update Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Strategy")
    t.add_column("Signing")
    t.add_column("Rollback")
    t.add_column("Verify")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(
            p.id, p.name, p.strategy,
            "[green]yes[/green]" if p.signing_required else "[red]no[/red]",
            "[green]yes[/green]" if p.rollback_enabled else "no",
            p.verification_mode,
            (p.content_hash or "")[:16] + "…" if p.content_hash else "—",
        )
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    strategy: str = typer.Option("full", "--strategy", "-s"),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
    signing_required: bool = typer.Option(True, "--signing/--no-signing"),
    rollback_enabled: bool = typer.Option(True, "--rollback/--no-rollback"),
    rollback_window_days: int = typer.Option(30, "--rollback-days"),
    max_delta_size_mb: Optional[int] = typer.Option(None, "--max-delta-mb"),
    verification_mode: str = typer.Option("strict", "--verify"),
) -> None:
    """Create a new update profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = upd.create_update_profile(
                s, name, strategy, distribution_id, description,
                signing_required, rollback_enabled, rollback_window_days,
                max_delta_size_mb, verification_mode,
            )
            s.commit()
            console.print(f"[green]Created[/green] update profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("show")
def show_profile(ctx: typer.Context, profile_id: str) -> None:
    """Show an update profile and its sub-resources."""
    with sync_session(_db(ctx)) as s:
        try:
            p = upd.get_update_profile(s, profile_id)
            channels = upd.list_update_channels(s, profile_id)
            targets = upd.list_recovery_targets(s, profile_id)
            hooks = upd.list_update_hooks(s, profile_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.rule(f"[cyan]{p.name}[/cyan]  ({p.id})")
    console.print(f"  strategy:       {p.strategy}")
    console.print(f"  signing:        {p.signing_required}")
    console.print(f"  rollback:       {p.rollback_enabled} ({p.rollback_window_days}d)")
    console.print(f"  verify:         {p.verification_mode}")
    if p.max_delta_size_mb:
        console.print(f"  max-delta:      {p.max_delta_size_mb} MB")
    console.print(f"  content-hash:   {p.content_hash or '—'}")

    if channels:
        t = Table(title="Update Channels")
        t.add_column("Name", style="cyan")
        t.add_column("Priority")
        t.add_column("Default?")
        t.add_column("URL")
        for ch in channels:
            t.add_row(
                ch.name, str(ch.priority),
                "[green]yes[/green]" if ch.is_default else "no",
                ch.url or "",
            )
        console.print(t)

    if targets:
        t = Table(title="Recovery Targets")
        t.add_column("Name", style="cyan")
        t.add_column("Type")
        t.add_column("Default?")
        t.add_column("Priority")
        for tg in targets:
            t.add_row(
                tg.name, tg.target_type,
                "[green]yes[/green]" if tg.is_default else "no",
                str(tg.priority),
            )
        console.print(t)

    if hooks:
        t = Table(title="Update Hooks")
        t.add_column("Hook Point", style="cyan")
        t.add_column("Priority")
        t.add_column("Enabled")
        t.add_column("Script (preview)")
        for h in hooks:
            preview = h.script_content[:60].replace("\n", " ") + (
                "…" if len(h.script_content) > 60 else ""
            )
            t.add_row(
                h.hook_point, str(h.priority),
                "[green]yes[/green]" if h.is_enabled else "[red]no[/red]",
                preview,
            )
        console.print(t)


@app.command("update")
def update_profile(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
    signing_required: Optional[bool] = typer.Option(None, "--signing/--no-signing"),
    rollback_enabled: Optional[bool] = typer.Option(None, "--rollback/--no-rollback"),
    rollback_window_days: Optional[int] = typer.Option(None, "--rollback-days"),
    verification_mode: Optional[str] = typer.Option(None, "--verify"),
    description: Optional[str] = typer.Option(None, "--desc"),
) -> None:
    """Update profile settings."""
    updates: dict = {}
    if strategy is not None:
        updates["strategy"] = strategy
    if signing_required is not None:
        updates["signing_required"] = signing_required
    if rollback_enabled is not None:
        updates["rollback_enabled"] = rollback_enabled
    if rollback_window_days is not None:
        updates["rollback_window_days"] = rollback_window_days
    if verification_mode is not None:
        updates["verification_mode"] = verification_mode
    if description is not None:
        updates["description"] = description

    with sync_session(_db(ctx)) as s:
        try:
            upd.update_update_profile(s, profile_id, **updates)
            s.commit()
            console.print(f"[green]Updated[/green] profile [cyan]{profile_id}[/cyan]")
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


@app.command("channel-add")
def channel_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    name: str = typer.Argument(...),
    priority: int = typer.Option(0, "--priority"),
    url: Optional[str] = typer.Option(None, "--url"),
    signing_key_id: Optional[str] = typer.Option(None, "--key"),
    is_default: bool = typer.Option(False, "--default/--no-default"),
) -> None:
    """Add or update an update channel."""
    with sync_session(_db(ctx)) as s:
        try:
            ch = upd.add_update_channel(
                s, profile_id, name, priority, url, signing_key_id, is_default
            )
            s.commit()
            console.print(
                f"[green]Set[/green] channel [cyan]{ch.name}[/cyan] "
                f"in profile [cyan]{profile_id}[/cyan]"
            )
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Recovery targets
# ---------------------------------------------------------------------------


@app.command("recovery-add")
def recovery_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    name: str = typer.Argument(...),
    target_type: str = typer.Argument(..., help="minimal | factory-reset | emergency-shell | network-boot | user-data-wipe"),
    kernel_args: Optional[str] = typer.Option(None, "--kernel-args"),
    initramfs_hint: Optional[str] = typer.Option(None, "--initramfs"),
    is_default: bool = typer.Option(False, "--default/--no-default"),
    priority: int = typer.Option(0, "--priority"),
) -> None:
    """Add or update a recovery boot target."""
    with sync_session(_db(ctx)) as s:
        try:
            t = upd.add_recovery_target(
                s, profile_id, name, target_type,
                kernel_args, initramfs_hint, is_default, priority,
            )
            s.commit()
            console.print(
                f"[green]Set[/green] recovery target [cyan]{t.name}[/cyan] "
                f"({t.target_type}) in profile [cyan]{profile_id}[/cyan]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


@app.command("hook-add")
def hook_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    hook_point: str = typer.Argument(..., help="pre-download | post-download | pre-apply | post-apply | post-reboot | rollback"),
    script_content: str = typer.Argument(...),
    priority: int = typer.Option(0, "--priority"),
    is_enabled: bool = typer.Option(True, "--enabled/--disabled"),
) -> None:
    """Add or update a lifecycle hook."""
    with sync_session(_db(ctx)) as s:
        try:
            h = upd.add_update_hook(
                s, profile_id, hook_point, script_content, priority, is_enabled
            )
            s.commit()
            console.print(
                f"[green]Set[/green] hook [cyan]{h.hook_point}[/cyan] "
                f"(prio={h.priority}) in profile [cyan]{profile_id}[/cyan]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show_update: bool = typer.Option(False, "--update", help="Print update config"),
    show_recovery: bool = typer.Option(False, "--recovery", help="Print recovery config"),
) -> None:
    """Render update / recovery configuration and store hash."""
    with sync_session(_db(ctx)) as s:
        try:
            p = upd.render_update_config(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show_update and p.rendered_update_config:
        console.rule("Update Config")
        console.print(p.rendered_update_config)
    if show_recovery and p.rendered_recovery_config:
        console.rule("Recovery Config")
        console.print(p.rendered_recovery_config)
