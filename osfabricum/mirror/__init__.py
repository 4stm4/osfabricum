"""M51 — Cache / Mirror / Offline designer."""

from osfabricum.mirror.service import (
    VALID_CACHE_POLICIES,
    add_cache_rule,
    add_mirror_endpoint,
    create_mirror_profile,
    get_mirror_profile,
    list_cache_policy_kinds,
    list_cache_rules,
    list_mirror_endpoints,
    list_mirror_profiles,
    render_mirror_config,
    update_mirror_profile,
)

__all__ = [
    "VALID_CACHE_POLICIES",
    "add_cache_rule",
    "add_mirror_endpoint",
    "create_mirror_profile",
    "get_mirror_profile",
    "list_cache_policy_kinds",
    "list_cache_rules",
    "list_mirror_endpoints",
    "list_mirror_profiles",
    "render_mirror_config",
    "update_mirror_profile",
]
