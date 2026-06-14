"""``osfabricumctl network`` — Network Designer CLI (M45)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import network as net

network_app = typer.Typer(
    help="Manage network configuration profiles (M45)", no_args_is_help=True
)

_DbUrl = Annotated[
    str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
]

_console = Console()


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _print_json(data: Any) -> None:
    _console.print_json(json.dumps(data, default=str))


@network_app.command("kind-list")
def kind_list(db_url: _DbUrl = None) -> None:
    """List seeded network interface kinds."""
    items = net.list_interface_kinds(db_url=db_url)
    t = Table(title="Network Interface Kinds")
    t.add_column("#", style="dim")
    t.add_column("Name")
    t.add_column("Description")
    for k in items:
        t.add_row(str(k["display_order"]), k["name"], k["description"])
    _console.print(t)


@network_app.command("list")
def list_profiles(
    distribution_id: Annotated[str | None, typer.Option("--distribution-id", "-d")] = None,
    db_url: _DbUrl = None,
) -> None:
    """List network profiles."""
    profiles = net.list_network_profiles(distribution_id, db_url=db_url)
    t = Table(title="Network Profiles")
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("Hostname")
    t.add_column("Rendered")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p["hostname"],
            "✓" if p["content_hash"] else "",
        )
    _console.print(t)


@network_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    hostname: Annotated[str, typer.Option("--hostname", "-H")] = "localhost",
    distribution_id: Annotated[str | None, typer.Option("--distribution-id", "-d")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new network profile."""
    try:
        result = net.create_network_profile(
            name, hostname=hostname, distribution_id=distribution_id, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of a network profile."""
    try:
        result = net.get_network_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    hostname: Annotated[str | None, typer.Option("--hostname", "-H")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update hostname / name (clears rendered cache)."""
    try:
        result = net.update_network_profile(
            profile_id, name=name, hostname=hostname, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("iface-add")
def iface_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n")],
    kind: Annotated[str, typer.Option("--kind", "-k")] = "ethernet",
    description: Annotated[str, typer.Option("--description")] = "",
    mtu: Annotated[int | None, typer.Option("--mtu")] = None,
    mac: Annotated[str | None, typer.Option("--mac")] = None,
    dhcp4: Annotated[bool, typer.Option("--dhcp4/--no-dhcp4")] = True,
    dhcp6: Annotated[bool, typer.Option("--dhcp6/--no-dhcp6")] = False,
    address: Annotated[list[str] | None, typer.Option("--address", "-a")] = None,
    gateway4: Annotated[str | None, typer.Option("--gateway")] = None,
    metric: Annotated[int | None, typer.Option("--metric")] = None,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    vlan_id: Annotated[int | None, typer.Option("--vlan-id")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Add a network interface to a profile."""
    try:
        result = net.add_interface(
            profile_id,
            name,
            kind,
            description=description,
            mtu=mtu,
            mac_address=mac,
            is_dhcp4=dhcp4,
            is_dhcp6=dhcp6,
            static_addresses=address or None,
            gateway4=gateway4,
            metric=metric,
            parent_name=parent,
            vlan_id=vlan_id,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("dns-add")
def dns_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    nameserver: Annotated[str, typer.Option("--ns", "-n")],
    search: Annotated[str | None, typer.Option("--search", "-s")] = None,
    priority: Annotated[int, typer.Option("--priority")] = 100,
    db_url: _DbUrl = None,
) -> None:
    """Add a DNS nameserver to a profile."""
    try:
        result = net.add_dns_entry(
            profile_id, nameserver, search_domain=search, priority=priority, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("route-add")
def route_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    destination: Annotated[str, typer.Option("--dest", "-d")],
    gateway: Annotated[str, typer.Option("--gw", "-g")],
    metric: Annotated[int, typer.Option("--metric")] = 0,
    iface: Annotated[str | None, typer.Option("--iface", "-i")] = None,
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: _DbUrl = None,
) -> None:
    """Add a static route to a profile."""
    try:
        result = net.add_route(
            profile_id, destination, gateway,
            metric=metric, interface_name=iface, description=description, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("rule-add")
def rule_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    chain: Annotated[str, typer.Option("--chain", "-c")],
    action: Annotated[str, typer.Option("--action", "-a")] = "ACCEPT",
    protocol: Annotated[str, typer.Option("--protocol", "-p")] = "any",
    source: Annotated[str | None, typer.Option("--source")] = None,
    destination: Annotated[str | None, typer.Option("--destination")] = None,
    dport: Annotated[str | None, typer.Option("--dport")] = None,
    priority: Annotated[int, typer.Option("--priority")] = 100,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Add a firewall rule to a profile."""
    try:
        result = net.add_firewall_rule(
            profile_id, chain, protocol, action,
            source_cidr=source, destination_cidr=destination,
            dport=dport, priority=priority, comment=comment, db_url=db_url
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@network_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Generate systemd-networkd config, resolv.conf, hosts and store on profile."""
    try:
        result = net.render_network_config(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _console.print(f"[green]✓[/green] content_hash: {result['content_hash']}")
    _console.print(
        f"   interfaces={result['interface_count']}  "
        f"dns={result['dns_count']}  "
        f"routes={result['route_count']}  "
        f"rules={result['firewall_rule_count']}"
    )
    _console.rule("systemd-networkd")
    _console.print(result["rendered_networkd"] or "(empty)")
    _console.rule("/etc/resolv.conf")
    _console.print(result["rendered_resolv_conf"])
    _console.rule("/etc/hosts")
    _console.print(result["rendered_hosts"])
    _console.rule("firewall summary")
    _console.print(result["rendered_firewall"])
