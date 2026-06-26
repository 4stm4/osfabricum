"""OSFabricum .ofpkg package builder and installer (M9).

Importing this package also registers all built-in package builders in the
registry so that the coordinator can look them up by name without a hardcoded
dispatch table.
"""

from osfabricum.packaging.builder import build_ofpkg
from osfabricum.packaging.installer import install_ofpkg, verify_ofpkg

# Import builder modules to trigger @register() side-effects
from osfabricum.packaging import (  # noqa: F401
    busybox,
    dropbear,
    hostapd,
    nanodhcp,
    tinywifi,
    xterm_pkg,
    openbox_pkg,
    xorgserver,
)

__all__ = ["build_ofpkg", "verify_ofpkg", "install_ofpkg"]
