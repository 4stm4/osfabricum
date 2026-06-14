"""``osfabricumctl security`` sub-commands (M47)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import hardening as hd

hardening_app = typer.Typer(
    name="security",
    help="Security / Hardening Designer (M47)",
    no_args_is_help=True,
)
console = Console()


def _db(db_url: str | None) -> str | None:
    return db_url


# ---------------------------------------------------------------------------
# MAC kinds
# ---------------------------------------------------------------------------


@hardening_app.command("mac-list")
def mac_list(
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """List seeded MAC framework kinds."""
    kinds = hd.list_mac_kinds(db_url=_db(db_url))
    tbl = Table("Name", "Description")
    for k in kinds:
        tbl.add_row(k["name"], k["description"])
    console.print(tbl)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@hardening_app.command("list")
def list_profiles(
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """List security profiles."""
    profiles = hd.list_security_profiles(
        distribution_id=distribution_id, db_url=_db(db_url)
    )
    tbl = Table("ID", "Name", "MAC Policy", "Hash")
    for p in profiles:
        tbl.add_row(
            p["id"][:8],
            p["name"],
            p["mac_policy"],
            (p["content_hash"] or "")[:16],
        )
    console.print(tbl)


@hardening_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[str | None, typer.Option("--dist")] = None,
    mac_policy: Annotated[str, typer.Option("--mac-policy")] = "none",
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Create a new security profile."""
    try:
        p = hd.create_security_profile(
            name,
            distribution_id=distribution_id,
            mac_policy=mac_policy,
            description=description,
            db_url=_db(db_url),
        )
        console.print(f"[green]created[/green] {p['id']} ({p['name']})")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


@hardening_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Show full security profile details."""
    try:
        p = hd.get_security_profile(profile_id, db_url=_db(db_url))
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    console.print(f"[bold]{p['name']}[/bold] ({p['id']})")
    console.print(f"  mac_policy:   {p['mac_policy']}")
    console.print(f"  description:  {p['description'] or '—'}")
    console.print(f"  content_hash: {p['content_hash'] or '—'}")

    if p["sysctl"]:
        tbl = Table("Key", "Value", "Description")
        for sc in p["sysctl"]:
            tbl.add_row(sc["key"], sc["value"], sc["description"] or "—")
        console.print(tbl)

    if p["mac_rules"]:
        tbl = Table("Subject", "Enforcing", "Priority", "Comment")
        for mr in p["mac_rules"]:
            tbl.add_row(
                mr["subject"],
                "yes" if mr["is_enforcing"] else "no",
                str(mr["priority"]),
                mr["comment"] or "—",
            )
        console.print(tbl)

    if p["pam_rules"]:
        tbl = Table("Service", "Type", "Flag", "Module")
        for pr in p["pam_rules"]:
            tbl.add_row(
                pr["service"], pr["module_type"], pr["control_flag"], pr["module_path"]
            )
        console.print(tbl)

    if p["capabilities"]:
        tbl = Table("Executable", "Add", "Drop", "NoNewPrivs")
        for cg in p["capabilities"]:
            tbl.add_row(
                cg["executable"],
                cg["add_caps"] or "—",
                cg["drop_caps"] or "—",
                "yes" if cg["no_new_privs"] else "no",
            )
        console.print(tbl)


@hardening_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    mac_policy: Annotated[str | None, typer.Option("--mac-policy")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Update security profile fields."""
    try:
        p = hd.update_security_profile(
            profile_id,
            name=name,
            mac_policy=mac_policy,
            description=description,
            db_url=_db(db_url),
        )
        console.print(f"[green]updated[/green] {p['id']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Sysctl
# ---------------------------------------------------------------------------


@hardening_app.command("sysctl-set")
def sysctl_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    key: Annotated[str, typer.Option("--key", help="e.g. net.ipv4.ip_forward")],
    value: Annotated[str, typer.Option("--value")],
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Set (upsert) a kernel sysctl parameter."""
    try:
        sc = hd.set_sysctl(
            profile_id, key, value, description=description, db_url=_db(db_url)
        )
        console.print(f"[green]set[/green] {sc['key']} = {sc['value']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# MAC rules
# ---------------------------------------------------------------------------


@hardening_app.command("mac-add")
def mac_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    subject: Annotated[str, typer.Option("--subject", help="Executable path or label")],
    rule: Annotated[str, typer.Option("--rule", help="Raw policy rule text")],
    enforcing: Annotated[bool, typer.Option("--enforce/--permissive")] = True,
    priority: Annotated[int, typer.Option("--priority")] = 100,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Add a MAC policy rule to a profile."""
    try:
        mr = hd.add_mac_rule(
            profile_id,
            subject,
            rule,
            is_enforcing=enforcing,
            priority=priority,
            comment=comment,
            db_url=_db(db_url),
        )
        mode = "enforce" if mr["is_enforcing"] else "permissive"
        console.print(f"[green]added[/green] MAC rule for {mr['subject']} ({mode})")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# PAM rules
# ---------------------------------------------------------------------------


@hardening_app.command("pam-add")
def pam_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    service: Annotated[str, typer.Option("--service", help="e.g. sshd, login")],
    module_type: Annotated[str, typer.Option("--type", help="auth|account|session|password")],
    control_flag: Annotated[str, typer.Option("--flag", help="required|requisite|sufficient|optional|include|substack")],
    module_path: Annotated[str, typer.Option("--module", help="e.g. pam_unix.so")],
    module_args: Annotated[str | None, typer.Option("--args")] = None,
    priority: Annotated[int, typer.Option("--priority")] = 100,
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Add a PAM service configuration entry."""
    try:
        pr = hd.add_pam_rule(
            profile_id,
            service,
            module_type,
            control_flag,
            module_path,
            module_args=module_args,
            priority=priority,
            db_url=_db(db_url),
        )
        console.print(
            f"[green]added[/green] PAM {pr['service']}/{pr['module_type']} "
            f"{pr['control_flag']} {pr['module_path']}"
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Capability grants
# ---------------------------------------------------------------------------


@hardening_app.command("cap-set")
def cap_set(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    executable: Annotated[str, typer.Option("--exe", help="Full path to executable")],
    add_caps: Annotated[str | None, typer.Option("--add")] = None,
    drop_caps: Annotated[str | None, typer.Option("--drop")] = None,
    no_new_privs: Annotated[bool, typer.Option("--no-new-privs/--allow-new-privs")] = False,
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Set (upsert) capability grants/drops for an executable."""
    try:
        cg = hd.set_capability_grant(
            profile_id,
            executable,
            add_caps=add_caps,
            drop_caps=drop_caps,
            no_new_privs=no_new_privs,
            description=description,
            db_url=_db(db_url),
        )
        console.print(f"[green]set[/green] capabilities for {cg['executable']}")
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@hardening_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: Annotated[
        str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")
    ] = None,
) -> None:
    """Render security config (sysctl, MAC rules, PAM, capabilities) and store hash."""
    try:
        result = hd.render_security_config(profile_id, db_url=_db(db_url))
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    console.print(f"[green]rendered[/green] {result['content_hash']}")
    console.print(f"  sysctl:       {result['sysctl_count']}")
    console.print(f"  MAC rules:    {result['mac_rule_count']}")
    console.print(f"  PAM rules:    {result['pam_rule_count']}")
    console.print(f"  capabilities: {result['capability_count']}")
    if result["rendered_sysctl"]:
        console.print("\n[bold]sysctl:[/bold]")
        console.print(result["rendered_sysctl"][:600])
