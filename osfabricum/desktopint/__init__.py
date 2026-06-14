"""Desktop Integration Designer — M42."""

from osfabricum.desktopint.service import (
    DEFAULT_USER_DIRS,
    VALID_ASSOCIATION_TYPES,
    VALID_CONDITIONS,
    VALID_XDG_DIRS,
    add_autostart_entry,
    add_mime_association,
    create_desktop_integration_profile,
    get_desktop_integration_profile,
    list_desktop_integration_profiles,
    list_mime_types,
    render_desktop_integration,
    set_user_dir,
    update_desktop_integration_profile,
)

__all__ = [
    "DEFAULT_USER_DIRS",
    "VALID_ASSOCIATION_TYPES",
    "VALID_CONDITIONS",
    "VALID_XDG_DIRS",
    "add_autostart_entry",
    "add_mime_association",
    "create_desktop_integration_profile",
    "get_desktop_integration_profile",
    "list_desktop_integration_profiles",
    "list_mime_types",
    "render_desktop_integration",
    "set_user_dir",
    "update_desktop_integration_profile",
]
