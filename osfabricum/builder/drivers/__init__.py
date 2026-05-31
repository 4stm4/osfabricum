"""Driver registry — maps ``build_system`` name → driver class (M8)."""

from __future__ import annotations

from osfabricum.builder.drivers.autotools import AutotoolsDriver
from osfabricum.builder.drivers.base import BuildDriver
from osfabricum.builder.drivers.cargo import CargoDriver
from osfabricum.builder.drivers.cmake import CMakeDriver
from osfabricum.builder.drivers.custom import CustomDriver
from osfabricum.builder.drivers.make import MakeDriver
from osfabricum.builder.drivers.meson import MesonDriver

#: Registry mapping ``build_system`` identifiers to their driver class.
DRIVERS: dict[str, type[BuildDriver]] = {
    "cargo": CargoDriver,
    "make": MakeDriver,
    "cmake": CMakeDriver,
    "meson": MesonDriver,
    "autotools": AutotoolsDriver,
    "custom": CustomDriver,
}

__all__ = [
    "DRIVERS",
    "BuildDriver",
    "AutotoolsDriver",
    "CargoDriver",
    "CMakeDriver",
    "CustomDriver",
    "MakeDriver",
    "MesonDriver",
]
