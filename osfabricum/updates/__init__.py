"""M49 — Update / OTA / Recovery Designer."""

from osfabricum.updates.service import (
    VALID_HOOK_POINTS,
    VALID_RECOVERY_TARGET_TYPES,
    VALID_STRATEGIES,
    VALID_VERIFICATION_MODES,
    add_recovery_target,
    add_update_channel,
    add_update_hook,
    create_update_profile,
    get_update_profile,
    list_recovery_targets,
    list_update_channels,
    list_update_hooks,
    list_update_profiles,
    list_update_strategy_kinds,
    render_update_config,
    update_update_profile,
)

__all__ = [
    "VALID_HOOK_POINTS",
    "VALID_RECOVERY_TARGET_TYPES",
    "VALID_STRATEGIES",
    "VALID_VERIFICATION_MODES",
    "add_recovery_target",
    "add_update_channel",
    "add_update_hook",
    "create_update_profile",
    "get_update_profile",
    "list_recovery_targets",
    "list_update_channels",
    "list_update_hooks",
    "list_update_profiles",
    "list_update_strategy_kinds",
    "render_update_config",
    "update_update_profile",
]
