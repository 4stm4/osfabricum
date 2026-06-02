"""Profile Designer (M27): full, versioned, diffable profiles as data.

The service layer here is the single home for profile write logic; the REST API
and the CLI are thin clients over it. A profile selects the universal entities
(class/board/kernel/toolchain/package_set/boot_scheme/image_recipe/branding/
graphical/network/security/update/validation) by name, and the resolver
consumes those selections (M27 closes audit gap G-02).
"""

from __future__ import annotations

from osfabricum.profile.schema import API_VERSION, KIND, REF_FIELDS, validate_doc
from osfabricum.profile.service import (
    clone_profile,
    create_profile,
    create_version,
    delete_profile,
    diff_profiles,
    export_profile,
    get_profile,
    import_profile,
    list_profiles,
    list_versions,
    update_profile,
)

__all__ = [
    "API_VERSION",
    "KIND",
    "REF_FIELDS",
    "clone_profile",
    "create_profile",
    "create_version",
    "delete_profile",
    "diff_profiles",
    "export_profile",
    "get_profile",
    "import_profile",
    "list_profiles",
    "list_versions",
    "update_profile",
    "validate_doc",
]
