"""OSFabricum — Users / Groups / Credentials / Secrets Designer (M44)."""

from osfabricum.users.service import (
    VALID_SECRET_KINDS,
    VALID_SHELL_PATHS,
    add_os_group,
    add_os_user,
    add_secret_variable,
    add_supplementary_group,
    create_user_profile,
    get_user_profile,
    list_user_profiles,
    list_user_shell_kinds,
    render_user_config,
    update_user_profile,
)

__all__ = [
    "VALID_SECRET_KINDS",
    "VALID_SHELL_PATHS",
    "add_os_group",
    "add_os_user",
    "add_secret_variable",
    "add_supplementary_group",
    "create_user_profile",
    "get_user_profile",
    "list_user_profiles",
    "list_user_shell_kinds",
    "render_user_config",
    "update_user_profile",
]
