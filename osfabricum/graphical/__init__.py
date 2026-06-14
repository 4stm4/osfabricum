"""Graphical Shell Designer — M40."""

from osfabricum.graphical.service import (
    COMPONENT_KINDS,
    DISPLAY_SERVERS,
    SESSION_TYPES,
    add_component,
    add_session,
    create_graphical_profile,
    get_graphical_profile,
    list_compositor_backends,
    list_display_manager_backends,
    list_graphical_profiles,
    render_session_config,
    update_graphical_profile,
    update_session,
)

__all__ = [
    "COMPONENT_KINDS",
    "DISPLAY_SERVERS",
    "SESSION_TYPES",
    "add_component",
    "add_session",
    "create_graphical_profile",
    "get_graphical_profile",
    "list_compositor_backends",
    "list_display_manager_backends",
    "list_graphical_profiles",
    "render_session_config",
    "update_graphical_profile",
    "update_session",
]
