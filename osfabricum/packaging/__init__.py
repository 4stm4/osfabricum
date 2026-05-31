"""OSFabricum .ofpkg package builder and installer (M9)."""

from osfabricum.packaging.builder import build_ofpkg
from osfabricum.packaging.installer import install_ofpkg, verify_ofpkg

__all__ = ["build_ofpkg", "verify_ofpkg", "install_ofpkg"]
