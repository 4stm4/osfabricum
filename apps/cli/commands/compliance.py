"""M48 — License / SBOM / Vuln / Source Compliance Designer CLI."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import compliance as cmp
from osfabricum.db.session import sync_session

app = typer.Typer(help="License / SBOM / Vuln / Source Compliance Designer (M48)")
console = Console()


def _db(ctx: typer.Context) -> str | None:
    try:
        return ctx.obj["db_url"]
    except (TypeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# SPDX kinds
# ---------------------------------------------------------------------------


@app.command("spdx-list")
def spdx_list(ctx: typer.Context) -> None:
    """List known SPDX license identifiers."""
    with sync_session(_db(ctx)) as s:
        kinds = cmp.list_spdx_license_kinds(s)
    t = Table(title="SPDX License Identifiers")
    t.add_column("SPDX ID", style="cyan")
    t.add_column("Name")
    t.add_column("Copyleft")
    t.add_column("Permissive")
    for k in kinds:
        t.add_row(
            k.spdx_id, k.name,
            "[red]yes[/red]" if k.is_copyleft else "no",
            "[green]yes[/green]" if k.is_permissive else "no",
        )
    console.print(t)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@app.command("list")
def list_profiles(
    ctx: typer.Context,
    distribution_id: Optional[str] = typer.Option(None, "--dist", help="Filter by distribution ID"),
) -> None:
    """List compliance profiles."""
    with sync_session(_db(ctx)) as s:
        profiles = cmp.list_compliance_profiles(s, distribution_id)
    t = Table(title="Compliance Profiles")
    t.add_column("ID", style="dim")
    t.add_column("Name", style="cyan")
    t.add_column("Copyleft")
    t.add_column("Proprietary")
    t.add_column("Block ≥")
    t.add_column("Hash", style="dim")
    for p in profiles:
        t.add_row(
            p.id, p.name,
            "[green]allow[/green]" if p.allow_copyleft else "[red]deny[/red]",
            "[red]allow[/red]" if p.allow_proprietary else "deny",
            p.min_vuln_severity_to_block,
            (p.content_hash or "")[:16] + "…" if p.content_hash else "—",
        )
    console.print(t)


@app.command("create")
def create_profile(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Profile name"),
    distribution_id: Optional[str] = typer.Option(None, "--dist"),
    description: str = typer.Option("", "--desc"),
    allow_copyleft: bool = typer.Option(True, "--allow-copyleft/--deny-copyleft"),
    allow_proprietary: bool = typer.Option(False, "--allow-proprietary/--deny-proprietary"),
    min_vuln_severity_to_block: str = typer.Option("critical", "--block-severity"),
    require_sbom: bool = typer.Option(True, "--require-sbom/--no-sbom"),
) -> None:
    """Create a new compliance profile."""
    with sync_session(_db(ctx)) as s:
        try:
            p = cmp.create_compliance_profile(
                s, name, distribution_id, description,
                allow_copyleft, allow_proprietary,
                min_vuln_severity_to_block, require_sbom,
            )
            s.commit()
            console.print(f"[green]Created[/green] compliance profile [cyan]{p.id}[/cyan]")
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


@app.command("show")
def show_profile(ctx: typer.Context, profile_id: str) -> None:
    """Show a compliance profile and its sub-resources."""
    with sync_session(_db(ctx)) as s:
        try:
            p = cmp.get_compliance_profile(s, profile_id)
            rules = cmp.list_license_rules(s, profile_id)
            gates = cmp.list_vuln_gates(s, profile_id)
            entries = cmp.list_sbom_entries(s, profile_id)
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.rule(f"[cyan]{p.name}[/cyan]  ({p.id})")
    console.print(f"  allow-copyleft:  {p.allow_copyleft}")
    console.print(f"  allow-proprietary: {p.allow_proprietary}")
    console.print(f"  block-severity:  {p.min_vuln_severity_to_block}")
    console.print(f"  require-sbom:    {p.require_sbom}")
    console.print(f"  content-hash:    {p.content_hash or '—'}")
    if p.description:
        console.print(f"  description:     {p.description}")

    if rules:
        t = Table(title="License Rules")
        t.add_column("SPDX ID", style="cyan")
        t.add_column("Policy")
        t.add_column("Reason")
        for r in rules:
            t.add_row(r.spdx_id, r.policy, r.reason or "")
        console.print(t)

    if gates:
        t = Table(title="Vuln Gates")
        t.add_column("CVE", style="cyan")
        t.add_column("Severity")
        t.add_column("Action")
        t.add_column("Package")
        for g in gates:
            t.add_row(
                g.cve_id, g.severity, g.action,
                g.package_name or "",
            )
        console.print(t)

    if entries:
        t = Table(title="SBOM Entries")
        t.add_column("Package", style="cyan")
        t.add_column("Version")
        t.add_column("SPDX ID")
        t.add_column("Source?")
        for e in entries:
            t.add_row(
                e.package_name, e.package_version,
                e.spdx_id or "—",
                "[green]yes[/green]" if e.is_source_available else "[red]no[/red]",
            )
        console.print(t)


@app.command("update")
def update_profile(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    allow_copyleft: Optional[bool] = typer.Option(None, "--allow-copyleft/--deny-copyleft"),
    allow_proprietary: Optional[bool] = typer.Option(None, "--allow-proprietary/--deny-proprietary"),
    min_vuln_severity_to_block: Optional[str] = typer.Option(None, "--block-severity"),
    require_sbom: Optional[bool] = typer.Option(None, "--require-sbom/--no-sbom"),
    description: Optional[str] = typer.Option(None, "--desc"),
) -> None:
    """Update compliance profile settings."""
    updates: dict = {}
    if allow_copyleft is not None:
        updates["allow_copyleft"] = allow_copyleft
    if allow_proprietary is not None:
        updates["allow_proprietary"] = allow_proprietary
    if min_vuln_severity_to_block is not None:
        updates["min_vuln_severity_to_block"] = min_vuln_severity_to_block
    if require_sbom is not None:
        updates["require_sbom"] = require_sbom
    if description is not None:
        updates["description"] = description

    with sync_session(_db(ctx)) as s:
        try:
            cmp.update_compliance_profile(s, profile_id, **updates)
            s.commit()
            console.print(f"[green]Updated[/green] profile [cyan]{profile_id}[/cyan]")
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# License rules
# ---------------------------------------------------------------------------


@app.command("license-set")
def license_set(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    spdx_id: str = typer.Argument(..., help="SPDX license identifier"),
    policy: str = typer.Argument(..., help="allow | deny | warn"),
    reason: Optional[str] = typer.Option(None, "--reason"),
) -> None:
    """Set (upsert) a license policy rule."""
    with sync_session(_db(ctx)) as s:
        try:
            r = cmp.set_license_rule(s, profile_id, spdx_id, policy, reason)
            s.commit()
            console.print(
                f"[green]Set[/green] {spdx_id} → {r.policy} in profile [cyan]{profile_id}[/cyan]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Vuln gates
# ---------------------------------------------------------------------------


@app.command("vuln-set")
def vuln_set(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    cve_id: str = typer.Argument(..., help="CVE identifier, e.g. CVE-2024-1234"),
    severity: str = typer.Argument(..., help="critical | high | medium | low | info"),
    action: str = typer.Argument(..., help="block | warn | ignore"),
    package_name: Optional[str] = typer.Option(None, "--package"),
    affected_version: Optional[str] = typer.Option(None, "--version"),
    reason: Optional[str] = typer.Option(None, "--reason"),
) -> None:
    """Set (upsert) a CVE gate entry."""
    with sync_session(_db(ctx)) as s:
        try:
            g = cmp.set_vuln_gate(
                s, profile_id, cve_id, severity, action,
                package_name, affected_version, reason,
            )
            s.commit()
            console.print(
                f"[green]Set[/green] {g.cve_id} → {g.action} in profile [cyan]{profile_id}[/cyan]"
            )
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# SBOM entries
# ---------------------------------------------------------------------------


@app.command("sbom-add")
def sbom_add(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    package_name: str = typer.Argument(...),
    package_version: str = typer.Argument(...),
    spdx_id: Optional[str] = typer.Option(None, "--spdx"),
    purl: Optional[str] = typer.Option(None, "--purl"),
    supplier: Optional[str] = typer.Option(None, "--supplier"),
    source_url: Optional[str] = typer.Option(None, "--source-url"),
    source_available: bool = typer.Option(True, "--source-available/--no-source"),
) -> None:
    """Add or update an SBOM entry."""
    with sync_session(_db(ctx)) as s:
        try:
            e = cmp.add_sbom_entry(
                s, profile_id, package_name, package_version,
                spdx_id, purl, supplier, source_url, source_available,
            )
            s.commit()
            console.print(
                f"[green]Added[/green] {e.package_name}@{e.package_version} "
                f"to profile [cyan]{profile_id}[/cyan]"
            )
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@app.command("render")
def render(
    ctx: typer.Context,
    profile_id: str = typer.Argument(...),
    show_sbom: bool = typer.Option(False, "--sbom", help="Print SBOM text"),
    show_vuln: bool = typer.Option(False, "--vuln", help="Print vuln report"),
    show_lic: bool = typer.Option(False, "--license", help="Print license report"),
) -> None:
    """Render compliance report and store hash."""
    with sync_session(_db(ctx)) as s:
        try:
            p = cmp.render_compliance_report(s, profile_id)
            s.commit()
        except KeyError as exc:
            console.print(f"[red]Not found:[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print(f"[green]Rendered[/green] {p.content_hash}")
    if show_sbom and p.rendered_sbom:
        console.rule("SBOM")
        console.print(p.rendered_sbom)
    if show_vuln and p.rendered_vuln_report:
        console.rule("Vuln Report")
        console.print(p.rendered_vuln_report)
    if show_lic and p.rendered_license_report:
        console.rule("License Report")
        console.print(p.rendered_license_report)
