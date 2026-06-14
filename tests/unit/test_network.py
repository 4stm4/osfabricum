"""Unit tests for M45 — Network Designer."""

from __future__ import annotations

import pytest

from osfabricum import network as net
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_network_interface_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_network.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_network_interface_kinds(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return net.create_network_profile("Primary", hostname="myhost.local", db_url=db_url)


@pytest.fixture()
def profile2(db_url):
    return net.create_network_profile("Secondary", db_url=db_url)


# ---------------------------------------------------------------------------
# Interface kinds
# ---------------------------------------------------------------------------


def test_list_kinds_seeded(db_url):
    kinds = net.list_interface_kinds(db_url=db_url)
    assert len(kinds) == 9
    names = {k["name"] for k in kinds}
    for expected in ("ethernet", "wifi", "loopback", "vlan", "bridge", "bond",
                     "dummy", "wireguard", "veth"):
        assert expected in names


def test_kinds_ordered(db_url):
    kinds = net.list_interface_kinds(db_url=db_url)
    orders = [k["display_order"] for k in kinds]
    assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile_defaults(db_url):
    p = net.create_network_profile("Net", db_url=db_url)
    assert p["hostname"] == "localhost"
    assert p["content_hash"] is None


def test_create_profile_custom_hostname(db_url, profile):
    assert profile["hostname"] == "myhost.local"


def test_create_duplicate_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        net.create_network_profile("Primary", db_url=db_url)


def test_create_same_name_different_dist(db_url, profile):
    p = net.create_network_profile("Primary", distribution_id="dist-x", db_url=db_url)
    assert p["id"] != profile["id"]


def test_list_profiles(db_url, profile, profile2):
    profiles = net.list_network_profiles(db_url=db_url)
    names = {p["name"] for p in profiles}
    assert "Primary" in names
    assert "Secondary" in names


def test_list_profiles_by_distribution(db_url):
    net.create_network_profile("A", distribution_id="d1", db_url=db_url)
    net.create_network_profile("B", distribution_id="d2", db_url=db_url)
    result = net.list_network_profiles("d1", db_url=db_url)
    assert len(result) == 1
    assert result[0]["name"] == "A"


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.get_network_profile("no-such", db_url=db_url)


def test_update_hostname(db_url, profile):
    updated = net.update_network_profile(
        profile["id"], hostname="router.home", db_url=db_url
    )
    assert updated["hostname"] == "router.home"


def test_update_name(db_url, profile):
    updated = net.update_network_profile(
        profile["id"], name="Renamed", db_url=db_url
    )
    assert updated["name"] == "Renamed"


def test_update_clears_cache(db_url, profile):
    net.add_interface(profile["id"], "lo", "loopback", db_url=db_url)
    net.render_network_config(profile["id"], db_url=db_url)
    updated = net.update_network_profile(
        profile["id"], hostname="new.host", db_url=db_url
    )
    assert updated["content_hash"] is None
    assert updated["rendered_networkd"] is None
    assert updated["rendered_resolv_conf"] is None


def test_update_nonexistent_raises(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.update_network_profile("bad-id", hostname="x", db_url=db_url)


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


def test_add_interface_defaults(db_url, profile):
    i = net.add_interface(profile["id"], "eth0", db_url=db_url)
    assert i["name"] == "eth0"
    assert i["kind"] == "ethernet"
    assert i["is_dhcp4"] is True
    assert i["is_dhcp6"] is False
    assert i["static_addresses"] == []
    assert i["gateway4"] is None
    assert i["mtu"] is None


def test_add_loopback(db_url, profile):
    i = net.add_interface(profile["id"], "lo", "loopback", db_url=db_url)
    assert i["kind"] == "loopback"


def test_add_static_interface(db_url, profile):
    i = net.add_interface(
        profile["id"], "eth0",
        is_dhcp4=False,
        static_addresses=["192.168.1.10/24", "10.0.0.1/8"],
        gateway4="192.168.1.1",
        mtu=9000,
        db_url=db_url,
    )
    assert i["is_dhcp4"] is False
    assert "192.168.1.10/24" in i["static_addresses"]
    assert "10.0.0.1/8" in i["static_addresses"]
    assert i["gateway4"] == "192.168.1.1"
    assert i["mtu"] == 9000


def test_add_vlan_interface(db_url, profile):
    i = net.add_interface(
        profile["id"], "eth0.100", "vlan",
        parent_name="eth0", vlan_id=100, db_url=db_url
    )
    assert i["kind"] == "vlan"
    assert i["parent_name"] == "eth0"
    assert i["vlan_id"] == 100


def test_add_bridge_interface(db_url, profile):
    i = net.add_interface(profile["id"], "br0", "bridge", db_url=db_url)
    assert i["kind"] == "bridge"


def test_add_all_kinds(db_url, profile):
    for idx, kind in enumerate(sorted(net.VALID_INTERFACE_KINDS)):
        net.add_interface(profile["id"], f"iface{idx}", kind, db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    assert len(detail["interfaces"]) == len(net.VALID_INTERFACE_KINDS)


def test_add_duplicate_interface_raises(db_url, profile):
    net.add_interface(profile["id"], "eth0", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        net.add_interface(profile["id"], "eth0", db_url=db_url)


def test_add_invalid_kind_raises(db_url, profile):
    with pytest.raises(ValueError, match="unknown interface kind"):
        net.add_interface(profile["id"], "eth0", "token-ring", db_url=db_url)


def test_add_interface_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.add_interface("bad-id", "eth0", db_url=db_url)


def test_get_profile_includes_interfaces(db_url, profile):
    net.add_interface(profile["id"], "lo", "loopback", db_url=db_url)
    net.add_interface(profile["id"], "eth0", db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    names = {i["name"] for i in detail["interfaces"]}
    assert {"lo", "eth0"} <= names


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------


def test_add_dns_entry(db_url, profile):
    d = net.add_dns_entry(profile["id"], "8.8.8.8", db_url=db_url)
    assert d["nameserver"] == "8.8.8.8"
    assert d["priority"] == 100
    assert d["search_domain"] is None


def test_add_dns_with_search(db_url, profile):
    d = net.add_dns_entry(
        profile["id"], "1.1.1.1", search_domain="example.com", priority=50, db_url=db_url
    )
    assert d["search_domain"] == "example.com"
    assert d["priority"] == 50


def test_add_duplicate_dns_raises(db_url, profile):
    net.add_dns_entry(profile["id"], "8.8.8.8", db_url=db_url)
    with pytest.raises(ValueError, match="already in"):
        net.add_dns_entry(profile["id"], "8.8.8.8", db_url=db_url)


def test_add_dns_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.add_dns_entry("bad-id", "8.8.8.8", db_url=db_url)


def test_get_profile_includes_dns(db_url, profile):
    net.add_dns_entry(profile["id"], "8.8.8.8", db_url=db_url)
    net.add_dns_entry(profile["id"], "8.8.4.4", db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    ns_set = {d["nameserver"] for d in detail["dns"]}
    assert {"8.8.8.8", "8.8.4.4"} <= ns_set


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_add_route(db_url, profile):
    r = net.add_route(profile["id"], "0.0.0.0/0", "192.168.1.1", db_url=db_url)
    assert r["destination"] == "0.0.0.0/0"
    assert r["gateway"] == "192.168.1.1"
    assert r["metric"] == 0


def test_add_route_with_options(db_url, profile):
    r = net.add_route(
        profile["id"], "10.8.0.0/24", "10.0.0.1",
        metric=100, interface_name="wg0", description="VPN route",
        db_url=db_url,
    )
    assert r["metric"] == 100
    assert r["interface_name"] == "wg0"
    assert r["description"] == "VPN route"


def test_add_duplicate_route_raises(db_url, profile):
    net.add_route(profile["id"], "0.0.0.0/0", "192.168.1.1", db_url=db_url)
    with pytest.raises(ValueError, match="already in"):
        net.add_route(profile["id"], "0.0.0.0/0", "192.168.1.1", db_url=db_url)


def test_add_route_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.add_route("bad-id", "0.0.0.0/0", "192.168.1.1", db_url=db_url)


def test_get_profile_includes_routes(db_url, profile):
    net.add_route(profile["id"], "0.0.0.0/0", "192.168.1.1", db_url=db_url)
    net.add_route(profile["id"], "10.0.0.0/8", "10.0.0.1", db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    dests = {r["destination"] for r in detail["routes"]}
    assert {"0.0.0.0/0", "10.0.0.0/8"} <= dests


# ---------------------------------------------------------------------------
# Firewall rules
# ---------------------------------------------------------------------------


def test_add_firewall_rule_defaults(db_url, profile):
    fr = net.add_firewall_rule(
        profile["id"], "INPUT", "tcp", "ACCEPT",
        dport="22", db_url=db_url
    )
    assert fr["chain"] == "INPUT"
    assert fr["protocol"] == "tcp"
    assert fr["action"] == "ACCEPT"
    assert fr["dport"] == "22"
    assert fr["priority"] == 100


def test_add_firewall_rule_drop(db_url, profile):
    fr = net.add_firewall_rule(
        profile["id"], "INPUT", "any", "DROP",
        source_cidr="10.0.0.0/8", db_url=db_url
    )
    assert fr["action"] == "DROP"
    assert fr["source_cidr"] == "10.0.0.0/8"


def test_add_firewall_rule_forward(db_url, profile):
    fr = net.add_firewall_rule(
        profile["id"], "FORWARD", "any", "ACCEPT",
        comment="Allow forwarding", db_url=db_url
    )
    assert fr["chain"] == "FORWARD"
    assert fr["comment"] == "Allow forwarding"


def test_add_rule_invalid_chain(db_url, profile):
    with pytest.raises(ValueError, match="unknown chain"):
        net.add_firewall_rule(profile["id"], "PREROUTING", "tcp", "ACCEPT", db_url=db_url)


def test_add_rule_invalid_protocol(db_url, profile):
    with pytest.raises(ValueError, match="unknown protocol"):
        net.add_firewall_rule(profile["id"], "INPUT", "sctp", "ACCEPT", db_url=db_url)


def test_add_rule_invalid_action(db_url, profile):
    with pytest.raises(ValueError, match="unknown action"):
        net.add_firewall_rule(profile["id"], "INPUT", "tcp", "LOG", db_url=db_url)


def test_add_rule_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.add_firewall_rule("bad-id", "INPUT", "tcp", "ACCEPT", db_url=db_url)


def test_get_profile_includes_firewall_rules(db_url, profile):
    net.add_firewall_rule(profile["id"], "INPUT", "tcp", "ACCEPT", dport="22", db_url=db_url)
    net.add_firewall_rule(profile["id"], "INPUT", "tcp", "ACCEPT", dport="443", db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    ports = {fr["dport"] for fr in detail["firewall_rules"]}
    assert {"22", "443"} <= ports


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _setup_full_profile(profile_id: str, db_url: str) -> None:
    net.add_interface(profile_id, "lo", "loopback", db_url=db_url)
    net.add_interface(
        profile_id, "eth0", "ethernet",
        is_dhcp4=False,
        static_addresses=["192.168.1.10/24"],
        gateway4="192.168.1.1",
        db_url=db_url,
    )
    net.add_interface(
        profile_id, "eth0.100", "vlan",
        parent_name="eth0", vlan_id=100, is_dhcp4=True, db_url=db_url
    )
    net.add_dns_entry(profile_id, "8.8.8.8", search_domain="example.com", priority=10, db_url=db_url)
    net.add_dns_entry(profile_id, "8.8.4.4", priority=20, db_url=db_url)
    net.add_route(profile_id, "0.0.0.0/0", "192.168.1.1", metric=100, db_url=db_url)
    net.add_route(profile_id, "10.8.0.0/24", "10.0.0.1", interface_name="eth0", db_url=db_url)
    net.add_firewall_rule(profile_id, "INPUT", "tcp", "ACCEPT", dport="22", comment="SSH", db_url=db_url)
    net.add_firewall_rule(profile_id, "INPUT", "any", "DROP", priority=999, db_url=db_url)


def test_render_basic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["interface_count"] == 3
    assert result["dns_count"] == 2
    assert result["route_count"] == 2
    assert result["firewall_rule_count"] == 2


def test_render_networkd_contains_interfaces(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    nd = result["rendered_networkd"]
    assert "[Match]" in nd
    assert "Name=lo" in nd
    assert "Name=eth0" in nd
    assert "LinkLocalAddressing=yes" in nd


def test_render_networkd_static_address(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    nd = result["rendered_networkd"]
    assert "Address=192.168.1.10/24" in nd
    assert "Gateway=192.168.1.1" in nd


def test_render_networkd_dhcp(db_url, profile):
    net.add_interface(profile["id"], "eth1", is_dhcp4=True, is_dhcp6=True, db_url=db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    assert "DHCP=yes" in result["rendered_networkd"]


def test_render_networkd_vlan_has_netdev(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    nd = result["rendered_networkd"]
    assert "[NetDev]" in nd
    assert "Kind=vlan" in nd
    assert "[VLAN]" in nd
    assert "Id=100" in nd


def test_render_interface_specific_route(db_url, profile):
    net.add_interface(profile["id"], "eth0", db_url=db_url)
    net.add_route(
        profile["id"], "10.8.0.0/24", "10.0.0.1",
        interface_name="eth0", db_url=db_url
    )
    result = net.render_network_config(profile["id"], db_url=db_url)
    nd = result["rendered_networkd"]
    assert "[Route]" in nd
    assert "Destination=10.8.0.0/24" in nd


def test_render_resolv_conf_nameservers(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    resolv = result["rendered_resolv_conf"]
    assert "nameserver 8.8.8.8" in resolv
    assert "nameserver 8.8.4.4" in resolv


def test_render_resolv_conf_search(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    assert "search example.com" in result["rendered_resolv_conf"]


def test_render_resolv_empty(db_url, profile):
    result = net.render_network_config(profile["id"], db_url=db_url)
    assert "no nameservers configured" in result["rendered_resolv_conf"]


def test_render_hosts(db_url, profile):
    result = net.render_network_config(profile["id"], db_url=db_url)
    hosts = result["rendered_hosts"]
    assert "127.0.0.1" in hosts
    assert "myhost.local" in hosts
    assert "myhost" in hosts


def test_render_firewall_manifest(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = net.render_network_config(profile["id"], db_url=db_url)
    fw = result["rendered_firewall"]
    assert "iptables -A INPUT" in fw
    assert "ACCEPT" in fw
    assert "DROP" in fw
    assert "--dport 22" in fw


def test_render_deterministic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    r1 = net.render_network_config(profile["id"], db_url=db_url)
    r2 = net.render_network_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    net.render_network_config(profile["id"], db_url=db_url)
    detail = net.get_network_profile(profile["id"], db_url=db_url)
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None
    assert "[Match]" in (detail["rendered_networkd"] or "")
    assert "nameserver" in (detail["rendered_resolv_conf"] or "")
    assert "127.0.0.1" in (detail["rendered_hosts"] or "")


def test_render_empty_profile(db_url, profile):
    result = net.render_network_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["interface_count"] == 0


def test_render_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        net.render_network_config("bad-id", db_url=db_url)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_valid_interface_kinds():
    expected = {"ethernet", "wifi", "loopback", "vlan", "bridge",
                "bond", "dummy", "wireguard", "veth"}
    assert net.VALID_INTERFACE_KINDS == expected


def test_valid_chains():
    assert net.VALID_CHAINS == {"INPUT", "OUTPUT", "FORWARD"}


def test_valid_protocols():
    assert net.VALID_PROTOCOLS == {"tcp", "udp", "icmp", "any"}


def test_valid_actions():
    assert net.VALID_ACTIONS == {"ACCEPT", "DROP", "REJECT"}
