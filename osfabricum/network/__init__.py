"""OSFabricum — Network Designer (M45)."""

from osfabricum.network.service import (
    VALID_ACTIONS,
    VALID_CHAINS,
    VALID_INTERFACE_KINDS,
    VALID_PROTOCOLS,
    add_dns_entry,
    add_firewall_rule,
    add_interface,
    add_route,
    create_network_profile,
    get_network_profile,
    list_interface_kinds,
    list_network_profiles,
    render_network_config,
    update_network_profile,
)

__all__ = [
    "VALID_ACTIONS",
    "VALID_CHAINS",
    "VALID_INTERFACE_KINDS",
    "VALID_PROTOCOLS",
    "add_dns_entry",
    "add_firewall_rule",
    "add_interface",
    "add_route",
    "create_network_profile",
    "get_network_profile",
    "list_interface_kinds",
    "list_network_profiles",
    "render_network_config",
    "update_network_profile",
]
