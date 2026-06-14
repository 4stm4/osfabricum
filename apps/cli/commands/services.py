"""``osfabricumctl services`` sub-commands (M46)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import services as svc

services_app = typer.Typer(
    name="services",
    help="Service / Init / Device Manager Designer (M46)",
    no_args_is_help=True,
)
console = Console()


def _db(db_url: str | None) -> str | None:
    return db_url


# ---------------------------------------------------------------------------
# Init system kinds
# ---------------------------------------------------------------------------


@services_app.command("kind-list")
def kind_list(
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """List seeded init system kinds."""
    kinds = svc.list_init_system_kinds(db_url=_db(db_url))
    tbl = Table("Name", "Description")
    for k in kinds:
        tbl.add_row(k["name"], k["description"])
    console.print(tbl)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@services_app.command("list")
def list_profiles(
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """List service profiles."""
    profiles = svc.list_service_profiles(
        distribution_id=distribution_id, db_url=_db(db_url)
    )
    tbl = Table("ID", "Name", "Init System", "Hash")
    for p in profiles:
        tbl.add_row(
            p["id"][:8],
            p["name"],
            p["init_system"],
            (p["content_hash"] or "")[:16],
        )
    console.print(tbl)


@services_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    init_system: Annotated[str, typer.Option("--init-system")] = "systemd",
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Create a new service profile."""
    try:
        p = svc.create_service_profile(
            name,
            distribution_id=distribution_id,
            init_system=init_system,
            description=description,
            db_url=_db(db_url),
        )
        console.print(f"[green]created[/green] {p['id']} ({p['name']})")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


@services_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Show full service profile details."""
    try:
        p = svc.get_service_profile(profile_id, db_url=_db(db_url))
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    console.print(f"[bold]{p['name']}[/bold] ({p['id']})")
    console.print(f"  init_system: {p['init_system']}")
    console.print(f"  description: {p['description'] or '—'}")
    console.print(f"  content_hash: {p['content_hash'] or '—'}")

    if p["entries"]:
        tbl = Table("Name", "Type", "Exec", "Restart", "Enabled")
        for e in p["entries"]:
            tbl.add_row(
                e["name"],
                e["unit_type"],
                (e["exec_start"] or "")[:40],
                e["restart_policy"],
                "yes" if e["is_enabled"] else "no",
            )
        console.print(tbl)

    if p["device_rules"]:
        tbl = Table("Subsystem", "Kernel", "Action", "Symlink", "Priority")
        for dr in p["device_rules"]:
            tbl.add_row(
                dr["subsystem"] or "—",
                dr["kernel_pattern"] or "—",
                dr["udev_action"],
                dr["symlink"] or "—",
                str(dr["priority"]),
            )
        console.print(tbl)

    if p["unit_overrides"]:
        tbl = Table("Unit", "Section")
        for uo in p["unit_overrides"]:
            tbl.add_row(uo["unit_name"], uo["section"])
        console.print(tbl)


@services_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    init_system: Annotated[str | None, typer.Option("--init-system")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Update service profile fields."""
    try:
        p = svc.update_service_profile(
            profile_id,
            name=name,
            init_system=init_system,
            description=description,
            db_url=_db(db_url),
        )
        console.print(f"[green]updated[/green] {p['id']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Service entries
# ---------------------------------------------------------------------------


@services_app.command("entry-add")
def entry_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", help="Unit name (without extension)")],
    unit_type: Annotated[str, typer.Option("--type")] = "service",
    exec_start: Annotated[str | None, typer.Option("--exec-start")] = None,
    restart_policy: Annotated[str, typer.Option("--restart")] = "no",
    wanted_by: Annotated[str, typer.Option("--wanted-by")] = "multi-user.target",
    description: Annotated[str, typer.Option("--description")] = "",
    run_user: Annotated[str | None, typer.Option("--user")] = None,
    run_group: Annotated[str | None, typer.Option("--group")] = None,
    is_enabled: Annotated[bool, typer.Option("--enabled/--disabled")] = True,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Add a service entry to a profile."""
    try:
        e = svc.add_service_entry(
            profile_id,
            name,
            unit_type=unit_type,
            exec_start=exec_start,
            restart_policy=restart_policy,
            wanted_by=wanted_by,
            description=description,
            run_user=run_user,
            run_group=run_group,
            is_enabled=is_enabled,
            db_url=_db(db_url),
        )
        console.print(f"[green]added[/green] {e['name']}.{e['unit_type']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Device rules
# ---------------------------------------------------------------------------


@services_app.command("rule-add")
def rule_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    subsystem: Annotated[str | None, typer.Option("--subsystem")] = None,
    kernel_pattern: Annotated[str | None, typer.Option("--kernel")] = None,
    udev_action: Annotated[str, typer.Option("--action")] = "add",
    symlink: Annotated[str | None, typer.Option("--symlink")] = None,
    mode: Annotated[str | None, typer.Option("--mode")] = None,
    owner: Annotated[str | None, typer.Option("--owner")] = None,
    group_name: Annotated[str | None, typer.Option("--group")] = None,
    priority: Annotated[int, typer.Option("--priority")] = 90,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Add a udev device rule to a profile."""
    try:
        dr = svc.add_device_rule(
            profile_id,
            subsystem=subsystem,
            kernel_pattern=kernel_pattern,
            udev_action=udev_action,
            symlink=symlink,
            mode=mode,
            owner=owner,
            group_name=group_name,
            priority=priority,
            comment=comment,
            db_url=_db(db_url),
        )
        console.print(f"[green]added[/green] device rule {dr['id'][:8]}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Unit overrides
# ---------------------------------------------------------------------------


@services_app.command("override-set")
def override_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    unit_name: Annotated[str, typer.Option("--unit", help="e.g. sshd.service")],
    content: Annotated[str, typer.Option("--content", help="Override .conf content")],
    section: Annotated[str, typer.Option("--section")] = "Service",
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Upsert a drop-in override fragment for an existing unit."""
    try:
        uo = svc.set_unit_override(
            profile_id,
            unit_name,
            content,
            section=section,
            db_url=_db(db_url),
        )
        console.print(f"[green]set[/green] override for {uo['unit_name']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@services_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Render service config (unit files, udev rules, overrides) and store hash."""
    try:
        result = svc.render_service_config(profile_id, db_url=_db(db_url))
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    console.print(f"[green]rendered[/green] {result['content_hash']}")
    console.print(f"  entries:      {result['entry_count']}")
    console.print(f"  device rules: {result['device_rule_count']}")
    console.print(f"  overrides:    {result['override_count']}")
    if result["rendered_units"]:
        console.print("\n[bold]Units:[/bold]")
        console.print(result["rendered_units"][:800])
    if result["rendered_udev"]:
        console.print("\n[bold]udev rules:[/bold]")
        console.print(result["rendered_udev"][:400])
