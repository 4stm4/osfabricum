"""Canonical seed data for the Universal OS Builder Model (M25).

The distribution classes and boot schemes below are fixed enumerations that the
core ships with — not user catalog data. They are the single source of truth
shared by migration ``0006`` (which seeds them into a freshly-upgraded database)
and by :func:`seed_distribution_classes` / :func:`seed_boot_schemes` (used by
tests and by metadata-built databases). The seed helpers are idempotent: they
insert only the rows that are not already present, keyed by ``name``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import BootScheme, DistributionClass

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# (name, description) — order is the canonical display order.
DISTRIBUTION_CLASSES: list[tuple[str, str]] = [
    ("embedded", "Headless embedded device firmware/OS"),
    ("router", "Network router / access-point OS"),
    ("server", "General-purpose or infrastructure server OS"),
    ("desktop", "Workstation OS with a graphical session"),
    ("kiosk", "Single-application locked-down OS"),
    ("appliance", "Purpose-built turnkey appliance OS"),
    ("mobile-handheld", "Mobile / handheld device OS"),
    ("recovery", "Recovery / rescue / installer environment"),
    ("firmware", "Low-level firmware image"),
    ("container-host", "Minimal OS for running containers"),
    ("hypervisor-host", "Minimal OS for running virtual machines"),
]

BOOT_SCHEMES: list[tuple[str, str]] = [
    ("direct-kernel", "Kernel booted directly (e.g. QEMU -kernel)"),
    ("rpi-firmware", "Raspberry Pi firmware boot (start*.elf / config.txt)"),
    ("u-boot", "Das U-Boot bootloader"),
    ("grub", "GRUB bootloader"),
    ("systemd-boot", "systemd-boot EFI stub loader"),
    ("efi", "Generic EFI boot"),
    ("pxe-netboot", "PXE / network boot"),
    ("custom-vendor", "Vendor-specific custom boot chain"),
]


def seed_distribution_classes(session: Session) -> int:
    """Insert any missing distribution classes. Returns the number added."""
    existing = {c.name for c in session.scalars(select(DistributionClass)).all()}
    added = 0
    for name, description in DISTRIBUTION_CLASSES:
        if name in existing:
            continue
        session.add(DistributionClass(name=name, description=description))
        added += 1
    if added:
        session.flush()
    return added


def seed_boot_schemes(session: Session) -> int:
    """Insert any missing boot schemes. Returns the number added."""
    existing = {b.name for b in session.scalars(select(BootScheme)).all()}
    added = 0
    for name, description in BOOT_SCHEMES:
        if name in existing:
            continue
        session.add(BootScheme(name=name, description=description))
        added += 1
    if added:
        session.flush()
    return added
