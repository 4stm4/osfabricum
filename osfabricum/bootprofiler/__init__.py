"""M66 — Boot / Performance Profiler public API."""

from osfabricum.bootprofiler.service import (
    VALID_CAPTURE_METHODS,
    VALID_EVENT_KINDS,
    add_boot_sample,
    create_boot_profile,
    get_boot_profile,
    list_boot_profiles,
    list_boot_samples,
    render_boot_timeline,
)

__all__ = [
    "VALID_CAPTURE_METHODS",
    "VALID_EVENT_KINDS",
    "add_boot_sample",
    "create_boot_profile",
    "get_boot_profile",
    "list_boot_profiles",
    "list_boot_samples",
    "render_boot_timeline",
]
