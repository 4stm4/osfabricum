"""Initramfs / Early Boot management (M32)."""

from osfabricum.initramfs.service import (
    add_initramfs_hook,
    add_initramfs_package,
    add_initramfs_script,
    create_initramfs_artifact,
    create_initramfs_profile,
    get_initramfs_profile,
    list_initramfs_profiles,
    resolve_initramfs,
    validate_initramfs_profile,
)

__all__ = [
    "create_initramfs_profile",
    "list_initramfs_profiles",
    "get_initramfs_profile",
    "add_initramfs_package",
    "add_initramfs_script",
    "add_initramfs_hook",
    "resolve_initramfs",
    "validate_initramfs_profile",
    "create_initramfs_artifact",
]

# Made with Bob
