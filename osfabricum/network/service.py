"""Network Designer service (M45).

A ``NetworkProfile`` captures the full network configuration for a
distribution image: interfaces (Ethernet, WiFi, VLAN, bridge, bond,
WireGuard…), DNS nameservers, static routes, and firewall rules.

Key functions:

* :func:`create_network_profile` — create a new network profile.
* :func:`get_network_profile` — full detail (interfaces, DNS, routes, rules).
* :func:`update_network_profile` — change hostname; clears rendered cache.
* :func:`add_interface` — declare a network interface with addressing options.
* :func:`add_dns_entry` — add a DNS nameserver / search domain.
* :func:`add_route` — add a static IP route.
* :func:`add_firewall_rule` — add a firewall rule.
* :func:`render_network_config` — generate systemd-networkd files,
  /etc/resolv.conf, /etc/hosts; compute sha256: content hash.
* :func:`list_interface_kinds` — enumerate the seeded interface kind lookup.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    NetDnsEntry,
    NetFirewallRule,
    NetInterface,
    NetRoute,
    NetworkInterfaceKind,
    NetworkProfile,
)
from osfabricum.db.seed_data import NETWORK_INTERFACE_KINDS
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_INTERFACE_KINDS: frozenset[str] = frozenset(
    name for name, *_ in NETWORK_INTERFACE_KINDS
)
VALID_CHAINS: frozenset[str] = frozenset({"INPUT", "OUTPUT", "FORWARD"})
VALID_PROTOCOLS: frozenset[str] = frozenset({"tcp", "udp", "icmp", "any"})
VALID_ACTIONS: frozenset[str] = frozenset({"ACCEPT", "DROP", "REJECT"})

# Kinds that require a .netdev file in systemd-networkd
_NETDEV_KINDS = frozenset({"vlan", "bridge", "bond", "dummy", "wireguard", "veth"})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _addrs(iface: NetInterface) -> list[str]:
    if not iface.static_addresses:
        return []
    try:
        return json.loads(iface.static_addresses)
    except (ValueError, TypeError):
        return []


def _profile_to_dict(p: NetworkProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "hostname": p.hostname,
        "rendered_networkd": p.rendered_networkd,
        "rendered_resolv_conf": p.rendered_resolv_conf,
        "rendered_hosts": p.rendered_hosts,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _clear_cache(p: NetworkProfile) -> None:
    p.rendered_networkd = None
    p.rendered_resolv_conf = None
    p.rendered_hosts = None
    p.content_hash = None
    p.rendered_at = None


# ---------------------------------------------------------------------------
# Interface kinds (seeded, read-only)
# ---------------------------------------------------------------------------


def list_interface_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": k.name,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in s.scalars(
                select(NetworkInterfaceKind).order_by(NetworkInterfaceKind.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_network_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    hostname: str = "localhost",
    db_url: str | None = None,
) -> dict[str, Any]:
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(NetworkProfile).where(
                NetworkProfile.distribution_id == distribution_id,
                NetworkProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"network profile already exists: {name!r}")
        p = NetworkProfile(
            name=name,
            distribution_id=distribution_id,
            hostname=hostname,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def list_network_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(NetworkProfile).order_by(NetworkProfile.name)
        if distribution_id is not None:
            q = q.where(NetworkProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_network_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile with interfaces, DNS entries, routes, and firewall rules."""
    with sync_session(db_url) as s:
        p = s.get(NetworkProfile, profile_id)
        if p is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["interfaces"] = [
            {
                "id": i.id,
                "name": i.name,
                "kind": i.kind,
                "description": i.description,
                "mtu": i.mtu,
                "mac_address": i.mac_address,
                "is_dhcp4": i.is_dhcp4,
                "is_dhcp6": i.is_dhcp6,
                "static_addresses": _addrs(i),
                "gateway4": i.gateway4,
                "metric": i.metric,
                "parent_name": i.parent_name,
                "vlan_id": i.vlan_id,
            }
            for i in s.scalars(
                select(NetInterface)
                .where(NetInterface.profile_id == profile_id)
                .order_by(NetInterface.name)
            ).all()
        ]

        result["dns"] = [
            {
                "id": d.id,
                "nameserver": d.nameserver,
                "search_domain": d.search_domain,
                "priority": d.priority,
            }
            for d in s.scalars(
                select(NetDnsEntry)
                .where(NetDnsEntry.profile_id == profile_id)
                .order_by(NetDnsEntry.priority, NetDnsEntry.nameserver)
            ).all()
        ]

        result["routes"] = [
            {
                "id": r.id,
                "destination": r.destination,
                "gateway": r.gateway,
                "metric": r.metric,
                "interface_name": r.interface_name,
                "description": r.description,
            }
            for r in s.scalars(
                select(NetRoute)
                .where(NetRoute.profile_id == profile_id)
                .order_by(NetRoute.metric, NetRoute.destination)
            ).all()
        ]

        result["firewall_rules"] = [
            {
                "id": fr.id,
                "chain": fr.chain,
                "protocol": fr.protocol,
                "source_cidr": fr.source_cidr,
                "destination_cidr": fr.destination_cidr,
                "dport": fr.dport,
                "action": fr.action,
                "priority": fr.priority,
                "comment": fr.comment,
            }
            for fr in s.scalars(
                select(NetFirewallRule)
                .where(NetFirewallRule.profile_id == profile_id)
                .order_by(NetFirewallRule.priority, NetFirewallRule.chain)
            ).all()
        ]

        return result


def update_network_profile(
    profile_id: str,
    *,
    name: str | None = None,
    hostname: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update hostname / name; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(NetworkProfile, profile_id)
        if p is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        if name is not None:
            p.name = name
        if hostname is not None:
            p.hostname = hostname
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


def add_interface(
    profile_id: str,
    name: str,
    kind: str = "ethernet",
    *,
    description: str = "",
    mtu: int | None = None,
    mac_address: str | None = None,
    is_dhcp4: bool = True,
    is_dhcp6: bool = False,
    static_addresses: list[str] | None = None,
    gateway4: str | None = None,
    metric: int | None = None,
    parent_name: str | None = None,
    vlan_id: int | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a network interface to a profile."""
    if kind not in VALID_INTERFACE_KINDS:
        raise ValueError(
            f"unknown interface kind {kind!r}; "
            f"valid: {', '.join(sorted(VALID_INTERFACE_KINDS))}"
        )
    with sync_session(db_url) as s:
        if s.get(NetworkProfile, profile_id) is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        existing = s.scalars(
            select(NetInterface).where(
                NetInterface.profile_id == profile_id,
                NetInterface.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"interface {name!r} already exists in profile {profile_id!r}"
            )
        iface = NetInterface(
            profile_id=profile_id,
            name=name,
            kind=kind,
            description=description,
            mtu=mtu,
            mac_address=mac_address,
            is_dhcp4=is_dhcp4,
            is_dhcp6=is_dhcp6,
            static_addresses=json.dumps(static_addresses) if static_addresses else None,
            gateway4=gateway4,
            metric=metric,
            parent_name=parent_name,
            vlan_id=vlan_id,
        )
        s.add(iface)
        s.commit()
        return {
            "id": iface.id,
            "profile_id": profile_id,
            "name": name,
            "kind": kind,
            "description": description,
            "mtu": mtu,
            "mac_address": mac_address,
            "is_dhcp4": is_dhcp4,
            "is_dhcp6": is_dhcp6,
            "static_addresses": static_addresses or [],
            "gateway4": gateway4,
            "metric": metric,
            "parent_name": parent_name,
            "vlan_id": vlan_id,
        }


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


def add_dns_entry(
    profile_id: str,
    nameserver: str,
    *,
    search_domain: str | None = None,
    priority: int = 100,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a DNS nameserver to a network profile."""
    with sync_session(db_url) as s:
        if s.get(NetworkProfile, profile_id) is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        existing = s.scalars(
            select(NetDnsEntry).where(
                NetDnsEntry.profile_id == profile_id,
                NetDnsEntry.nameserver == nameserver,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"nameserver {nameserver!r} already in profile {profile_id!r}"
            )
        d = NetDnsEntry(
            profile_id=profile_id,
            nameserver=nameserver,
            search_domain=search_domain,
            priority=priority,
        )
        s.add(d)
        s.commit()
        return {
            "id": d.id,
            "profile_id": profile_id,
            "nameserver": nameserver,
            "search_domain": search_domain,
            "priority": priority,
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def add_route(
    profile_id: str,
    destination: str,
    gateway: str,
    *,
    metric: int = 0,
    interface_name: str | None = None,
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a static IP route to a network profile."""
    with sync_session(db_url) as s:
        if s.get(NetworkProfile, profile_id) is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        existing = s.scalars(
            select(NetRoute).where(
                NetRoute.profile_id == profile_id,
                NetRoute.destination == destination,
                NetRoute.gateway == gateway,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"route {destination!r} via {gateway!r} already in profile {profile_id!r}"
            )
        r = NetRoute(
            profile_id=profile_id,
            destination=destination,
            gateway=gateway,
            metric=metric,
            interface_name=interface_name,
            description=description,
        )
        s.add(r)
        s.commit()
        return {
            "id": r.id,
            "profile_id": profile_id,
            "destination": destination,
            "gateway": gateway,
            "metric": metric,
            "interface_name": interface_name,
            "description": description,
        }


# ---------------------------------------------------------------------------
# Firewall rules
# ---------------------------------------------------------------------------


def add_firewall_rule(
    profile_id: str,
    chain: str,
    protocol: str,
    action: str,
    *,
    source_cidr: str | None = None,
    destination_cidr: str | None = None,
    dport: str | None = None,
    priority: int = 100,
    comment: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a firewall rule to a network profile."""
    if chain not in VALID_CHAINS:
        raise ValueError(
            f"unknown chain {chain!r}; valid: {', '.join(sorted(VALID_CHAINS))}"
        )
    if protocol not in VALID_PROTOCOLS:
        raise ValueError(
            f"unknown protocol {protocol!r}; valid: {', '.join(sorted(VALID_PROTOCOLS))}"
        )
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"unknown action {action!r}; valid: {', '.join(sorted(VALID_ACTIONS))}"
        )
    with sync_session(db_url) as s:
        if s.get(NetworkProfile, profile_id) is None:
            raise ValueError(f"network profile not found: {profile_id!r}")
        fr = NetFirewallRule(
            profile_id=profile_id,
            chain=chain,
            protocol=protocol,
            action=action,
            source_cidr=source_cidr,
            destination_cidr=destination_cidr,
            dport=dport,
            priority=priority,
            comment=comment,
        )
        s.add(fr)
        s.commit()
        return {
            "id": fr.id,
            "profile_id": profile_id,
            "chain": chain,
            "protocol": protocol,
            "action": action,
            "source_cidr": source_cidr,
            "destination_cidr": destination_cidr,
            "dport": dport,
            "priority": priority,
            "comment": comment,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_NETWORKD_HEADER = "# Generated by OSFabricum M45 — do not edit manually\n"
_RESOLV_HEADER = "# /etc/resolv.conf — generated by OSFabricum M45\n"
_HOSTS_HEADER = "# /etc/hosts — generated by OSFabricum M45\n"


def _netdev_block(iface: NetInterface) -> str:
    """Return .netdev content for virtual interface kinds."""
    lines = [
        _NETWORKD_HEADER,
        "[NetDev]\n",
        f"Name={iface.name}\n",
        f"Kind={iface.kind}\n",
    ]
    if iface.mac_address:
        lines.append(f"MACAddress={iface.mac_address}\n")
    if iface.kind == "vlan" and iface.vlan_id is not None:
        lines.append("\n[VLAN]\n")
        lines.append(f"Id={iface.vlan_id}\n")
    return "".join(lines)


def _network_block(iface: NetInterface, routes: list[NetRoute]) -> str:
    """Return .network content for an interface."""
    lines = [
        _NETWORKD_HEADER,
        "[Match]\n",
        f"Name={iface.name}\n",
    ]
    if iface.mac_address and iface.kind == "ethernet":
        lines.append(f"MACAddress={iface.mac_address}\n")

    lines.append("\n[Network]\n")
    if iface.description:
        lines.append(f"Description={iface.description}\n")
    if iface.kind == "loopback":
        lines.append("LinkLocalAddressing=yes\n")
    else:
        if iface.is_dhcp4 and iface.is_dhcp6:
            lines.append("DHCP=yes\n")
        elif iface.is_dhcp4:
            lines.append("DHCP=ipv4\n")
        elif iface.is_dhcp6:
            lines.append("DHCP=ipv6\n")
        for addr in _addrs(iface):
            lines.append(f"Address={addr}\n")
        if iface.gateway4:
            lines.append(f"Gateway={iface.gateway4}\n")

    if iface.mtu:
        lines.append(f"\n[Link]\n")
        lines.append(f"MTUBytes={iface.mtu}\n")

    # Interface-specific static routes
    iface_routes = [r for r in routes if r.interface_name == iface.name]
    for r in sorted(iface_routes, key=lambda x: (x.metric, x.destination)):
        lines.append(f"\n[Route]\n")
        lines.append(f"Destination={r.destination}\n")
        lines.append(f"Gateway={r.gateway}\n")
        if r.metric:
            lines.append(f"Metric={r.metric}\n")

    return "".join(lines)


def _build_networkd(
    interfaces: list[NetInterface], routes: list[NetRoute]
) -> str:
    """Build concatenated systemd-networkd config content."""
    sorted_ifaces = sorted(
        interfaces,
        key=lambda i: (0 if i.kind == "loopback" else 1, i.name),
    )
    sections: list[str] = []
    for iface in sorted_ifaces:
        prefix = f"10-{iface.name}"
        if iface.kind in _NETDEV_KINDS:
            sections.append(
                f"##-- /etc/systemd/network/{prefix}.netdev --##\n"
                + _netdev_block(iface)
            )
        sections.append(
            f"##-- /etc/systemd/network/{prefix}.network --##\n"
            + _network_block(iface, routes)
        )
    return "\n".join(sections)


def _build_resolv_conf(dns_entries: list[NetDnsEntry]) -> str:
    sorted_dns = sorted(dns_entries, key=lambda d: (d.priority, d.nameserver))
    search_domains = sorted(
        {d.search_domain for d in sorted_dns if d.search_domain}
    )
    lines = [_RESOLV_HEADER]
    if search_domains:
        lines.append(f"search {' '.join(search_domains)}\n")
    for d in sorted_dns:
        lines.append(f"nameserver {d.nameserver}\n")
    if not sorted_dns:
        lines.append("# no nameservers configured\n")
    return "".join(lines)


def _build_hosts(hostname: str) -> str:
    short = hostname.split(".")[0]
    return (
        _HOSTS_HEADER
        + "127.0.0.1\tlocalhost\n"
        + "::1\t\tlocalhost\n"
        + f"127.0.1.1\t{hostname} {short}\n"
    )


def _firewall_manifest(rules: list[NetFirewallRule]) -> str:
    """Plain-text iptables-style comment block for the rendered output."""
    if not rules:
        return "# no firewall rules configured\n"
    lines = ["# Firewall rules (iptables-style summary)\n"]
    for r in sorted(rules, key=lambda x: (x.priority, x.chain)):
        src = f"-s {r.source_cidr} " if r.source_cidr else ""
        dst = f"-d {r.destination_cidr} " if r.destination_cidr else ""
        proto = f"-p {r.protocol} " if r.protocol != "any" else ""
        port = f"--dport {r.dport} " if r.dport else ""
        cmt = f"  # {r.comment}" if r.comment else ""
        lines.append(
            f"iptables -A {r.chain} {proto}{src}{dst}{port}-j {r.action}{cmt}\n"
        )
    return "".join(lines)


def render_network_config(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate systemd-networkd files, /etc/resolv.conf, /etc/hosts; store on row.

    All outputs are concatenated for the deterministic sha256: hash.
    """
    with sync_session(db_url) as s:
        p = s.get(NetworkProfile, profile_id)
        if p is None:
            raise ValueError(f"network profile not found: {profile_id!r}")

        interfaces = s.scalars(
            select(NetInterface).where(NetInterface.profile_id == profile_id)
        ).all()
        dns_entries = s.scalars(
            select(NetDnsEntry).where(NetDnsEntry.profile_id == profile_id)
        ).all()
        routes = s.scalars(
            select(NetRoute).where(NetRoute.profile_id == profile_id)
        ).all()
        firewall_rules = s.scalars(
            select(NetFirewallRule).where(NetFirewallRule.profile_id == profile_id)
        ).all()

        networkd = _build_networkd(list(interfaces), list(routes))
        resolv = _build_resolv_conf(list(dns_entries))
        hosts = _build_hosts(p.hostname)
        fw_manifest = _firewall_manifest(list(firewall_rules))

        body = networkd + "\n---\n" + resolv + "\n---\n" + hosts + "\n---\n" + fw_manifest
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_networkd = networkd
        p.rendered_resolv_conf = resolv
        p.rendered_hosts = hosts
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_networkd": networkd,
            "rendered_resolv_conf": resolv,
            "rendered_hosts": hosts,
            "rendered_firewall": fw_manifest,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "interface_count": len(interfaces),
            "dns_count": len(dns_entries),
            "route_count": len(routes),
            "firewall_rule_count": len(firewall_rules),
        }
