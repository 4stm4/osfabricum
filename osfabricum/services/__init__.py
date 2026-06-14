"""Service / Init / Device Manager Designer public API (M46)."""

from osfabricum.services.service import (
    VALID_INIT_SYSTEMS,
    VALID_RESTART_POLICIES,
    VALID_UDEV_ACTIONS,
    VALID_UNIT_TYPES,
    VALID_OVERRIDE_SECTIONS,
    add_device_rule,
    add_service_entry,
    create_service_profile,
    get_service_profile,
    list_init_system_kinds,
    list_service_profiles,
    render_service_config,
    set_unit_override,
    update_service_profile,
)

__all__ = [
    "VALID_INIT_SYSTEMS",
    "VALID_RESTART_POLICIES",
    "VALID_UDEV_ACTIONS",
    "VALID_UNIT_TYPES",
    "VALID_OVERRIDE_SECTIONS",
    "add_device_rule",
    "add_service_entry",
    "create_service_profile",
    "get_service_profile",
    "list_init_system_kinds",
    "list_service_profiles",
    "render_service_config",
    "set_unit_override",
    "update_service_profile",
]
