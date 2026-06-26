"""Canonical seed data for the Universal OS Builder Model (M25).

The distribution classes and boot schemes below are fixed enumerations that the
core ships with — not user catalog data. They are the single source of truth
shared by migration ``0006`` (which seeds them into a freshly-upgraded database)
and by :func:`seed_distribution_classes` / :func:`seed_boot_schemes` (used by
tests and by metadata-built databases). The seed helpers are idempotent: they
insert only the rows that are not already present, keyed by ``name``.

M30 adds BSP seed data loaders that read from YAML files in catalog/seed/.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml
from sqlalchemy import select

from osfabricum.db.models import (
    AppCategory,
    Board,
    InitSystemKind,
    MimeTypeDefinition,
    NetworkInterfaceKind,
    SecurityMacKind,
    SpdxLicenseKind,
    ThemeAssetKind,
    UpdateStrategyKind,
    SDKExportKind,
    CachePolicyKind,
    ProbeSourceKind,
    LayerKind,
    OverrideKind,
    PatchTargetKind,
    GraphKind,
    ExplainTraceKind,
    DiffReportKind,
    RollbackKind,
    UserShellKind,
    BoardDeviceTree,
    BoardFirmware,
    BoardFlashMethod,
    BoardProbeProfile,
    BoardRevision,
    BoardTestMethod,
    BootScheme,
    CompositorBackend,
    DisplayManagerBackend,
    DistributionClass,
    PackageKind,
    PackageLayer,
    RuntimePackageBackend,
    SocFamily,
)

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

# M35: package taxonomy. Every package has exactly one kind. (name, description)
PACKAGE_KINDS: list[tuple[str, str]] = [
    ("system", "Core system package"),
    ("boot", "Bootloader / boot artifact package"),
    ("kernel-module", "In-tree or external kernel module (kernel-bound)"),
    ("driver", "Hardware driver package (kernel-bound)"),
    ("firmware", "Device firmware blob package"),
    ("runtime", "Language/runtime support package"),
    ("library", "Shared/static library package"),
    ("service", "Background service / daemon package"),
    ("desktop", "Desktop environment / graphical shell package"),
    ("application", "End-user application package"),
    ("theme", "Theme / appearance package"),
    ("branding", "Branding / identity package"),
    ("development", "Development tooling package"),
    ("debug", "Debug symbols / debugging package"),
    ("test", "Test / validation package"),
    ("documentation", "Documentation package"),
    ("locale", "Locale / translation package"),
    ("meta", "Meta-package (selection only, no payload)"),
]

# M35: package layers, ordered lowest → highest. (name, position, description)
PACKAGE_LAYERS: list[tuple[str, int, str]] = [
    ("base", 0, "Base userland"),
    ("hardware", 1, "Hardware enablement"),
    ("boot", 2, "Boot chain"),
    ("kernel", 3, "Kernel and modules"),
    ("system", 4, "System services and core OS"),
    ("runtime", 5, "Language runtimes"),
    ("services", 6, "Background services"),
    ("desktop", 7, "Desktop / graphical stack"),
    ("applications", 8, "End-user applications"),
    ("branding", 9, "Branding and identity"),
    ("development", 10, "Development tooling"),
    ("debug", 11, "Debug symbols"),
    ("test", 12, "Test / validation"),
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


def seed_package_kinds(session: Session) -> int:
    """Insert any missing package kinds (M35). Returns the number added."""
    existing = {k.name for k in session.scalars(select(PackageKind)).all()}
    added = 0
    for name, description in PACKAGE_KINDS:
        if name in existing:
            continue
        session.add(PackageKind(name=name, description=description))
        added += 1
    if added:
        session.flush()
    return added


def seed_package_layers(session: Session) -> int:
    """Insert any missing package layers (M35). Returns the number added."""
    existing = {layer.name for layer in session.scalars(select(PackageLayer)).all()}
    added = 0
    for name, position, description in PACKAGE_LAYERS:
        if name in existing:
            continue
        session.add(PackageLayer(name=name, position=position, description=description))
        added += 1
    if added:
        session.flush()
    return added


# M38: runtime package backends. (name, description, config_template)
# {feed_name}, {feed_url}, {channel} are substituted by render_policy.
RUNTIME_BACKENDS: list[tuple[str, str, str]] = [
    ("none", "No package manager — immutable or build-time-only image", ""),
    (
        "osf-pkg",
        "OSFabricum native package manager",
        "# OSFabricum package feed\nfeed {feed_name} {feed_url}\nchannel {channel}\n",
    ),
    (
        "opkg",
        "opkg (OpenWRT-compatible lightweight package manager)",
        "src/gz {feed_name} {feed_url}\n",
    ),
    (
        "apk",
        "Alpine Package Keeper (apk) — used by Alpine and musl-based images",
        "{feed_url}\n",
    ),
    (
        "dpkg",
        "dpkg/apt-compatible package manager (Debian/Ubuntu style)",
        "deb {feed_url} {channel} main\n",
    ),
    (
        "rpm",
        "rpm/dnf-compatible package manager (Red Hat style)",
        "[{feed_name}]\nbaseurl={feed_url}\nenabled=1\ngpgcheck=1\n",
    ),
]


def seed_runtime_backends(session: Session) -> int:
    """Insert any missing runtime package backends (M38). Returns the number added."""
    existing = {b.name for b in session.scalars(select(RuntimePackageBackend)).all()}
    added = 0
    for name, description, config_template in RUNTIME_BACKENDS:
        if name in existing:
            continue
        session.add(
            RuntimePackageBackend(
                name=name, description=description, config_template=config_template
            )
        )
        added += 1
    if added:
        session.flush()
    return added


# ---------------------------------------------------------------------------
# M40: Graphical Shell seed data
# ---------------------------------------------------------------------------

# (name, description, protocol, package_name, config_template)
COMPOSITOR_BACKENDS: list[tuple[str, str, str, str, str]] = [
    ("none", "No compositor / headless", "none", "", ""),
    (
        "mutter",
        "GNOME Mutter (Wayland + X11 via Xwayland)",
        "both",
        "mutter",
        "",
    ),
    (
        "kwin",
        "KDE KWin compositor (Wayland + X11)",
        "both",
        "kwin",
        "",
    ),
    (
        "sway",
        "i3-compatible Wayland compositor (wlroots)",
        "wayland",
        "sway",
        "# sway config\noutput * bg {wallpaper} fill\n",
    ),
    (
        "labwc",
        "Openbox-like Wayland compositor (wlroots)",
        "wayland",
        "labwc",
        "",
    ),
    (
        "hyprland",
        "Dynamic tiling Wayland compositor",
        "wayland",
        "hyprland",
        "",
    ),
    (
        "openbox",
        "Classic X11 stacking window manager",
        "x11",
        "openbox",
        "",
    ),
    (
        "xfwm4",
        "XFCE window manager (X11)",
        "x11",
        "xfwm4",
        "",
    ),
    (
        "marco",
        "MATE window manager (X11)",
        "x11",
        "marco",
        "",
    ),
    (
        "icewm",
        "Lightweight X11 window manager",
        "x11",
        "icewm",
        "",
    ),
]

# (name, description, package_name, config_template)
DISPLAY_MANAGER_BACKENDS: list[tuple[str, str, str, str]] = [
    ("none", "No display manager (getty / auto-login)", "", ""),
    (
        "gdm",
        "GNOME Display Manager (Wayland-native)",
        "gdm",
        "",
    ),
    (
        "lightdm",
        "LightDM — flexible, greeter-based DM",
        "lightdm",
        "[Seat:*]\ngreeter-session={greeter}\nautologin-user={autologin_user}\n",
    ),
    (
        "sddm",
        "Simple Desktop Display Manager (KDE, Wayland-capable)",
        "sddm",
        "[Autologin]\nSession={session}\nUser={autologin_user}\n",
    ),
    (
        "greetd",
        "Minimal Wayland-native greeter daemon",
        "greetd",
        "[terminal]\nvt = 1\n\n[default_session]\ncommand = {greeter_cmd}\n",
    ),
    (
        "ly",
        "TUI display manager (ncurses)",
        "ly",
        "",
    ),
]


def seed_compositor_backends(session: Session) -> int:
    """Insert any missing compositor backends (M40). Returns the number added."""
    existing = {b.name for b in session.scalars(select(CompositorBackend)).all()}
    added = 0
    for name, description, protocol, package_name, config_template in COMPOSITOR_BACKENDS:
        if name in existing:
            continue
        session.add(
            CompositorBackend(
                name=name,
                description=description,
                protocol=protocol,
                package_name=package_name or None,
                config_template=config_template,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


# M41: application categories (name, description, icon, display_order)
APP_CATEGORIES: list[tuple[str, str, str | None, int]] = [
    ("productivity", "Word processors, spreadsheets, notes", "application-office", 0),
    ("internet", "Web browsers, email clients, messaging", "applications-internet", 1),
    ("multimedia", "Audio, video, photo and media tools", "applications-multimedia", 2),
    ("graphics", "Image editors, viewers and design tools", "applications-graphics", 3),
    ("office", "Office suites, PDF tools, document viewers", "applications-office", 4),
    ("development", "IDEs, editors, debuggers, version control", "applications-development", 5),
    ("games", "Games and entertainment", "applications-games", 6),
    ("utilities", "System tools, file managers, archivers", "applications-utilities", 7),
    ("system", "Core system administration tools", "applications-system", 8),
    ("education", "Educational apps and language tools", "applications-education", 9),
    ("accessibility", "Accessibility and assistive technologies", "preferences-desktop-accessibility", 10),
]

# M41: valid default-app role names
DEFAULT_APP_ROLES = (
    "web-browser",
    "text-editor",
    "file-manager",
    "terminal",
    "email-client",
    "music-player",
    "video-player",
    "image-viewer",
    "pdf-viewer",
    "archive-manager",
    "calculator",
    "calendar",
    "contacts",
    "camera",
)


def seed_display_manager_backends(session: Session) -> int:
    """Insert any missing display manager backends (M40). Returns the number added."""
    existing = {b.name for b in session.scalars(select(DisplayManagerBackend)).all()}
    added = 0
    for name, description, package_name, config_template in DISPLAY_MANAGER_BACKENDS:
        if name in existing:
            continue
        session.add(
            DisplayManagerBackend(
                name=name,
                description=description,
                package_name=package_name or None,
                config_template=config_template,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


# ---------------------------------------------------------------------------
# M30: BSP Seed Data Loaders
# ---------------------------------------------------------------------------


# M42: common MIME type definitions (name, description, parent, icon, display_order)
MIME_TYPE_DEFINITIONS: list[tuple[str, str, str | None, str | None, int]] = [
    ("text/html", "HTML document", "text/xml", "text-html", 0),
    ("text/plain", "Plain text file", None, "text-x-generic", 1),
    ("text/x-python", "Python source file", "text/plain", "text-x-python", 2),
    ("text/x-shellscript", "Shell script", "text/plain", "text-x-script", 3),
    ("text/markdown", "Markdown document", "text/plain", "text-x-generic", 4),
    ("image/jpeg", "JPEG image", None, "image-jpeg", 5),
    ("image/png", "PNG image", None, "image-png", 6),
    ("image/gif", "GIF image", None, "image-gif", 7),
    ("image/webp", "WebP image", None, "image-webp", 8),
    ("image/svg+xml", "SVG image", "text/xml", "image-svg+xml", 9),
    ("audio/mpeg", "MP3 audio", None, "audio-mpeg", 10),
    ("audio/ogg", "OGG audio", None, "audio-ogg", 11),
    ("audio/flac", "FLAC audio", None, "audio-x-flac", 12),
    ("video/mp4", "MP4 video", None, "video-mp4", 13),
    ("video/webm", "WebM video", None, "video-webm", 14),
    ("video/x-matroska", "Matroska video", None, "video-x-generic", 15),
    ("application/pdf", "PDF document", None, "application-pdf", 16),
    ("application/zip", "ZIP archive", None, "application-zip", 17),
    ("application/x-tar", "TAR archive", None, "application-x-tar", 18),
    ("application/x-7z-compressed", "7-Zip archive", None, "application-x-7z-compressed", 19),
    ("inode/directory", "Directory / folder", None, "folder", 20),
]

# M42: XDG user directory names and their default paths
XDG_USER_DIR_DEFAULTS: list[tuple[str, str]] = [
    ("DESKTOP", "Desktop"),
    ("DOWNLOAD", "Downloads"),
    ("DOCUMENTS", "Documents"),
    ("MUSIC", "Music"),
    ("PICTURES", "Pictures"),
    ("VIDEOS", "Videos"),
    ("TEMPLATES", "Templates"),
    ("PUBLICSHARE", "Public"),
]

# M42: valid autostart conditions and MIME association types
AUTOSTART_CONDITIONS = ("always", "graphical", "wayland", "x11")
MIME_ASSOCIATION_TYPES = ("default", "added", "removed")

# M42: valid XDG user directory names
XDG_DIR_NAMES = tuple(name for name, _ in XDG_USER_DIR_DEFAULTS)


def seed_app_categories(session: Session) -> int:
    """Insert any missing app categories (M41). Returns the number added."""
    existing = {c.name for c in session.scalars(select(AppCategory)).all()}
    added = 0
    for name, description, icon, display_order in APP_CATEGORIES:
        if name in existing:
            continue
        session.add(
            AppCategory(
                name=name,
                description=description,
                icon=icon,
                display_order=display_order,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


# M43: theme asset kinds (name, description, display_order)
THEME_ASSET_KINDS: list[tuple[str, str, int]] = [
    ("gtk-theme", "GTK 3/4 visual theme package", 0),
    ("icon-theme", "XDG icon theme package", 1),
    ("cursor-theme", "XDG cursor theme package", 2),
    ("sound-theme", "XDG sound / event-sound theme package", 3),
    ("font-face", "Font face package (TTF/OTF/variable)", 4),
    ("wallpaper", "Wallpaper image package", 5),
]


def seed_theme_asset_kinds(session: Session) -> int:
    """Insert any missing theme asset kinds (M43). Returns the number added."""
    existing = {k.name for k in session.scalars(select(ThemeAssetKind)).all()}
    added = 0
    for name, description, display_order in THEME_ASSET_KINDS:
        if name in existing:
            continue
        session.add(
            ThemeAssetKind(name=name, description=description, display_order=display_order)
        )
        added += 1
    if added:
        session.flush()
    return added


NETWORK_INTERFACE_KINDS: list[tuple[str, str, int]] = [
    ("ethernet", "Wired Ethernet interface", 0),
    ("wifi", "Wireless LAN interface (802.11)", 1),
    ("loopback", "Loopback interface", 2),
    ("vlan", "IEEE 802.1Q VLAN sub-interface", 3),
    ("bridge", "Software bridge (L2 switch)", 4),
    ("bond", "NIC bonding / link aggregation (802.3ad)", 5),
    ("dummy", "Dummy virtual interface", 6),
    ("wireguard", "WireGuard VPN tunnel", 7),
    ("veth", "Virtual Ethernet pair (containers)", 8),
]


def seed_network_interface_kinds(session: Session) -> int:
    """Insert any missing network interface kinds (M45). Returns the number added."""
    existing = {k.name for k in session.scalars(select(NetworkInterfaceKind)).all()}
    added = 0
    for name, description, display_order in NETWORK_INTERFACE_KINDS:
        if name in existing:
            continue
        session.add(
            NetworkInterfaceKind(
                name=name, description=description, display_order=display_order
            )
        )
        added += 1
    if added:
        session.flush()
    return added


USER_SHELL_KINDS: list[tuple[str, str, int]] = [
    ("/bin/sh", "POSIX shell", 0),
    ("/bin/bash", "Bourne Again shell", 1),
    ("/bin/zsh", "Z shell", 2),
    ("/bin/fish", "Friendly interactive shell", 3),
    ("/bin/dash", "Dash shell (lightweight)", 4),
    ("/usr/sbin/nologin", "No interactive login", 5),
    ("/bin/false", "Deny login (always exits 1)", 6),
]


def seed_user_shell_kinds(session: Session) -> int:
    """Insert any missing login shell kinds (M44). Returns the number added."""
    existing = {k.path for k in session.scalars(select(UserShellKind)).all()}
    added = 0
    for path, description, display_order in USER_SHELL_KINDS:
        if path in existing:
            continue
        session.add(
            UserShellKind(path=path, description=description, display_order=display_order)
        )
        added += 1
    if added:
        session.flush()
    return added


# (spdx_id, name, is_copyleft, is_permissive, display_order)
SPDX_LICENSE_KINDS: list[tuple[str, str, bool, bool, int]] = [
    ("MIT", "MIT License", False, True, 0),
    ("Apache-2.0", "Apache License 2.0", False, True, 1),
    ("BSD-2-Clause", "BSD 2-Clause \"Simplified\" License", False, True, 2),
    ("BSD-3-Clause", "BSD 3-Clause \"New\" or \"Revised\" License", False, True, 3),
    ("ISC", "ISC License", False, True, 4),
    ("MPL-2.0", "Mozilla Public License 2.0", True, False, 5),
    ("LGPL-2.1-only", "GNU Lesser General Public License v2.1 only", True, False, 6),
    ("LGPL-3.0-only", "GNU Lesser General Public License v3.0 only", True, False, 7),
    ("GPL-2.0-only", "GNU General Public License v2.0 only", True, False, 8),
    ("GPL-3.0-only", "GNU General Public License v3.0 only", True, False, 9),
    ("AGPL-3.0-only", "GNU Affero General Public License v3.0 only", True, False, 10),
    ("CC0-1.0", "Creative Commons Zero v1.0 Universal", False, True, 11),
    ("Proprietary", "Proprietary / Closed-source", False, False, 12),
    ("LicenseRef-Unknown", "Unknown or unclassified license", False, False, 13),
]


def seed_spdx_license_kinds(session: Session) -> int:
    """Insert any missing SPDX license kinds (M48). Returns the number added."""
    existing = {k.spdx_id for k in session.scalars(select(SpdxLicenseKind)).all()}
    added = 0
    for spdx_id, name, is_copyleft, is_permissive, display_order in SPDX_LICENSE_KINDS:
        if spdx_id in existing:
            continue
        session.add(
            SpdxLicenseKind(
                spdx_id=spdx_id,
                name=name,
                is_copyleft=is_copyleft,
                is_permissive=is_permissive,
                display_order=display_order,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


SECURITY_MAC_KINDS: list[tuple[str, str, int]] = [
    ("none", "No mandatory access control framework", 0),
    ("apparmor", "AppArmor — path-based MAC (Ubuntu, openSUSE, Debian)", 1),
    ("selinux", "SELinux — label-based MAC (Fedora, RHEL, Android)", 2),
    ("tomoyo", "TOMOYO Linux — pathname-based MAC", 3),
    ("smack", "SMACK — Simplified Mandatory Access Control Kernel", 4),
    ("landlock", "Landlock LSM — unprivileged sandboxing (Linux 5.13+)", 5),
]


def seed_security_mac_kinds(session: Session) -> int:
    """Insert any missing MAC framework kinds (M47). Returns the number added."""
    existing = {k.name for k in session.scalars(select(SecurityMacKind)).all()}
    added = 0
    for name, description, display_order in SECURITY_MAC_KINDS:
        if name in existing:
            continue
        session.add(
            SecurityMacKind(name=name, description=description, display_order=display_order)
        )
        added += 1
    if added:
        session.flush()
    return added


INIT_SYSTEM_KINDS: list[tuple[str, str, int]] = [
    ("systemd", "systemd — system and service manager", 0),
    ("openrc", "OpenRC — dependency-based init system", 1),
    ("s6", "s6 — skarnet.org supervision suite", 2),
    ("runit", "runit — UNIX init scheme with service supervision", 3),
    ("busybox-init", "BusyBox init — minimal sysvinit-compatible init", 4),
    ("dinit", "dinit — service manager with dependency ordering", 5),
    ("shepherd", "GNU Shepherd — extensible service manager (Guix)", 6),
]


def seed_init_system_kinds(session: Session) -> int:
    """Insert any missing init system kinds (M46). Returns the number added."""
    existing = {k.name for k in session.scalars(select(InitSystemKind)).all()}
    added = 0
    for name, description, display_order in INIT_SYSTEM_KINDS:
        if name in existing:
            continue
        session.add(
            InitSystemKind(name=name, description=description, display_order=display_order)
        )
        added += 1
    if added:
        session.flush()
    return added


def seed_mime_type_definitions(session: Session) -> int:
    """Insert any missing MIME type definitions (M42). Returns the number added."""
    existing = {m.name for m in session.scalars(select(MimeTypeDefinition)).all()}
    added = 0
    for name, description, parent, icon, display_order in MIME_TYPE_DEFINITIONS:
        if name in existing:
            continue
        session.add(
            MimeTypeDefinition(
                name=name,
                description=description,
                parent=parent,
                icon=icon,
                display_order=display_order,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


def seed_soc_families_from_yaml(session: Session, yaml_path: Path | str) -> int:
    """Load SoC families from YAML file. Returns the number added."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0

    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    if not data or "items" not in data:
        return 0

    existing = {s.name for s in session.scalars(select(SocFamily)).all()}
    added = 0

    for item in data["items"]:
        if item["name"] in existing:
            continue

        session.add(
            SocFamily(
                id=str(uuid4()),
                name=item["name"],
                vendor=item.get("vendor"),
                description=item.get("description"),
                metadata_json=item.get("metadata"),
            )
        )
        added += 1

    if added:
        session.flush()
    return added


def seed_board_revisions_from_yaml(session: Session, yaml_path: Path | str) -> int:
    """Load board revisions from YAML file. Returns the number added."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0

    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    if not data or "items" not in data:
        return 0

    # Get board and SoC family mappings (try both name and id)
    all_boards = session.scalars(select(Board)).all()
    boards = {}
    for b in all_boards:
        boards[b.name] = b.id
        boards[b.id] = b.id  # Also map by ID

    soc_families = {s.name: s.id for s in session.scalars(select(SocFamily)).all()}

    # Get existing revisions
    existing = {(r.board_id, r.revision) for r in session.scalars(select(BoardRevision)).all()}
    added = 0

    for item in data["items"]:
        board_name = item["board"]
        if board_name not in boards:
            continue

        board_id = boards[board_name]
        revision = item["revision"]

        if (board_id, revision) in existing:
            continue

        soc_family_id = None
        if "soc_family" in item and item["soc_family"] in soc_families:
            soc_family_id = soc_families[item["soc_family"]]

        session.add(
            BoardRevision(
                id=str(uuid4()),
                board_id=board_id,
                revision=revision,
                soc_family_id=soc_family_id,
                description=item.get("description"),
                is_default=item.get("is_default", False),
                metadata_json=item.get("metadata"),
            )
        )
        added += 1

    if added:
        session.flush()
    return added


def seed_board_bsp_from_yaml(session: Session, yaml_path: Path | str) -> dict[str, int]:
    """Load board BSP data from YAML file. Returns counts by type."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return {}

    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    if not data:
        return {}

    # Get board mapping (try both name and id)
    all_boards = session.scalars(select(Board)).all()
    boards = {}
    for b in all_boards:
        boards[b.name] = b.id
        boards[b.id] = b.id  # Also map by ID

    counts: dict[str, int] = {
        "firmware": 0,
        "device_trees": 0,
        "flash_methods": 0,
        "test_methods": 0,
        "probe_profiles": 0,
    }

    # Load firmware
    if "firmware" in data:
        existing = {(f.board_id, f.filename) for f in session.scalars(select(BoardFirmware)).all()}
        for item in data["firmware"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            filename = item["filename"]

            if (board_id, filename) in existing:
                continue

            session.add(
                BoardFirmware(
                    id=str(uuid4()),
                    board_id=board_id,
                    filename=filename,
                    source_uri=item.get("source_uri"),
                    source_ref=item.get("source_ref"),
                    expected_hash=item.get("expected_hash"),
                    required=item.get("required", True),
                    placement=item.get("placement"),
                    metadata_json=item.get("metadata"),
                )
            )
            counts["firmware"] += 1

    # Load device trees
    if "device_trees" in data:
        existing = {
            (d.board_id, d.filename) for d in session.scalars(select(BoardDeviceTree)).all()
        }
        for item in data["device_trees"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            filename = item["filename"]

            if (board_id, filename) in existing:
                continue

            session.add(
                BoardDeviceTree(
                    id=str(uuid4()),
                    board_id=board_id,
                    filename=filename,
                    dtb_type=item["dtb_type"],
                    source_uri=item.get("source_uri"),
                    source_ref=item.get("source_ref"),
                    expected_hash=item.get("expected_hash"),
                    required=item.get("required", True),
                    placement=item.get("placement"),
                    metadata_json=item.get("metadata"),
                )
            )
            counts["device_trees"] += 1

    # Load flash methods
    if "flash_methods" in data:
        existing = {
            (m.board_id, m.method_name) for m in session.scalars(select(BoardFlashMethod)).all()
        }
        for item in data["flash_methods"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            method_name = item["method_name"]

            if (board_id, method_name) in existing:
                continue

            requires_tools = item.get("requires_tools")
            session.add(
                BoardFlashMethod(
                    id=str(uuid4()),
                    board_id=board_id,
                    method_name=method_name,
                    description=item.get("description"),
                    command_template=item.get("command_template"),
                    requires_tools={"tools": requires_tools} if requires_tools else None,
                    device_pattern=item.get("device_pattern"),
                    is_default=item.get("is_default", False),
                    metadata_json=item.get("metadata"),
                )
            )
            counts["flash_methods"] += 1

    # Load test methods
    if "test_methods" in data:
        existing = {
            (m.board_id, m.method_name) for m in session.scalars(select(BoardTestMethod)).all()
        }
        for item in data["test_methods"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            method_name = item["method_name"]

            if (board_id, method_name) in existing:
                continue

            requires_tools = item.get("requires_tools")
            session.add(
                BoardTestMethod(
                    id=str(uuid4()),
                    board_id=board_id,
                    method_name=method_name,
                    description=item.get("description"),
                    test_command=item.get("test_command"),
                    requires_tools={"tools": requires_tools} if requires_tools else None,
                    timeout_seconds=item.get("timeout_seconds"),
                    is_default=item.get("is_default", False),
                    metadata_json=item.get("metadata"),
                )
            )
            counts["test_methods"] += 1

    # Load probe profiles
    if "probe_profiles" in data:
        existing = {
            (p.board_id, p.probe_method, p.match_pattern or "")
            for p in session.scalars(select(BoardProbeProfile)).all()
        }
        for item in data["probe_profiles"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            probe_method = item["probe_method"]
            match_pattern = item.get("match_pattern", "")

            if (board_id, probe_method, match_pattern) in existing:
                continue

            session.add(
                BoardProbeProfile(
                    id=str(uuid4()),
                    board_id=board_id,
                    probe_method=probe_method,
                    match_pattern=item.get("match_pattern"),
                    match_fields=item.get("match_fields"),
                    confidence=item.get("confidence", 100),
                    metadata_json=item.get("metadata"),
                )
            )
            counts["probe_profiles"] += 1

    if any(counts.values()):
        session.flush()

    return counts


def seed_boot_chains(session: Session, yaml_path: Path | None = None) -> dict[str, int]:
    """Load boot chain seed data from YAML (M31).

    Args:
        session: Database session
        yaml_path: Path to boot_chains.yaml (defaults to catalog/seed/boot_chains.yaml)

    Returns:
        Dictionary with counts of seeded items
    """
    from osfabricum.db.models import BootChain, BootChainBinding, BootChainFile, BootChainTemplate

    if yaml_path is None:
        yaml_path = Path(__file__).parent.parent.parent / "catalog" / "seed" / "boot_chains.yaml"

    if not yaml_path.exists():
        return {"boot_chains": 0, "templates": 0, "files": 0, "bindings": 0}

    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    counts: dict[str, int] = {
        "boot_chains": 0,
        "templates": 0,
        "files": 0,
        "bindings": 0,
    }

    # Load boot chains
    if "boot_chains" in data:
        existing_chains = {chain.id: chain for chain in session.scalars(select(BootChain)).all()}

        for item in data["boot_chains"]:
            chain_id = item["id"]

            # Skip if already exists
            if chain_id in existing_chains:
                continue

            # Create boot chain
            chain = BootChain(
                id=chain_id,
                name=item["name"],
                boot_scheme_id=item["boot_scheme_id"],
                description=item.get("description"),
                metadata_json=item.get("metadata"),
            )
            session.add(chain)
            session.flush()
            counts["boot_chains"] += 1

            # Add templates
            if "templates" in item:
                for tpl in item["templates"]:
                    template = BootChainTemplate(
                        id=str(uuid4()),
                        boot_chain_id=chain_id,
                        template_type=tpl["template_type"],
                        content=tpl["content"],
                        variables=tpl.get("variables"),
                    )
                    session.add(template)
                    counts["templates"] += 1

            # Add files
            if "files" in item:
                for file_item in item["files"]:
                    # Resolve template reference
                    content_template = file_item.get("content_template")
                    if isinstance(content_template, str) and not content_template.startswith("{{"):
                        # It's a template_type reference, find the template
                        for tpl in item.get("templates", []):
                            if tpl["template_type"] == content_template:
                                content_template = tpl["content"]
                                break

                    file_obj = BootChainFile(
                        id=str(uuid4()),
                        boot_chain_id=chain_id,
                        filename=file_item["filename"],
                        placement=file_item["placement"],
                        content_template=content_template,
                        template_id=None,  # Could be enhanced to link to template
                        required=file_item.get("required", True),
                        permissions=file_item.get("permissions"),
                    )
                    session.add(file_obj)
                    counts["files"] += 1

    # Load bindings
    if "boot_chain_bindings" in data:
        existing_bindings = {
            (b.boot_chain_id, b.board_id, b.profile_id)
            for b in session.scalars(select(BootChainBinding)).all()
        }

        for item in data["boot_chain_bindings"]:
            boot_chain_id = item["boot_chain_id"]
            board_id = item.get("board_id")
            profile_id = item.get("profile_id")

            if (boot_chain_id, board_id, profile_id) in existing_bindings:
                continue

            binding = BootChainBinding(
                id=str(uuid4()),
                boot_chain_id=boot_chain_id,
                board_id=board_id,
                profile_id=profile_id,
                is_default=item.get("is_default", False),
                priority=item.get("priority", 100),
            )
            session.add(binding)
            counts["bindings"] += 1

    if any(counts.values()):
        session.flush()

    return counts


def seed_initramfs_profiles(session: Session, yaml_path: Path | None = None) -> dict[str, int]:
    """Load initramfs profiles seed data from YAML (M32).

    Args:
        session: Database session
        yaml_path: Path to initramfs_profiles.yaml
            (defaults to catalog/seed/initramfs_profiles.yaml)

    Returns:
        Dictionary with counts of seeded items
    """
    from osfabricum.db.models import (
        InitramfsHook,
        InitramfsPackage,
        InitramfsProfile,
        InitramfsScript,
    )

    if yaml_path is None:
        yaml_path = (
            Path(__file__).parent.parent.parent / "catalog" / "seed" / "initramfs_profiles.yaml"
        )

    if not yaml_path.exists():
        return {"profiles": 0, "packages": 0, "scripts": 0, "hooks": 0}

    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    counts: dict[str, int] = {
        "profiles": 0,
        "packages": 0,
        "scripts": 0,
        "hooks": 0,
    }

    # Load initramfs profiles
    if "initramfs_profiles" in data:
        existing_profiles = {
            profile.id: profile for profile in session.scalars(select(InitramfsProfile)).all()
        }

        for item in data["initramfs_profiles"]:
            profile_id = item["id"]

            # Skip if already exists
            if profile_id in existing_profiles:
                continue

            # Create profile
            profile = InitramfsProfile(
                id=profile_id,
                name=item["name"],
                profile_type=item["profile_type"],
                description=item.get("description"),
                compression=item.get("compression", "zstd"),
                size_limit_mb=item.get("size_limit_mb"),
                include_modules=item.get("include_modules", True),
                include_firmware=item.get("include_firmware", False),
                enable_debug_shell=item.get("enable_debug_shell", False),
                enable_network=item.get("enable_network", False),
                enable_encryption_unlock=item.get("enable_encryption_unlock", False),
                enable_factory_reset=item.get("enable_factory_reset", False),
                metadata_json=item.get("metadata"),
            )
            session.add(profile)
            session.flush()
            counts["profiles"] += 1

            # Add packages
            if "packages" in item:
                for pkg in item["packages"]:
                    package = InitramfsPackage(
                        id=str(uuid4()),
                        initramfs_profile_id=profile_id,
                        package_name=pkg["package_name"],
                        version_constraint=pkg.get("version_constraint"),
                        required=pkg.get("required", True),
                        priority=pkg.get("priority", 100),
                        metadata_json=pkg.get("metadata"),
                    )
                    session.add(package)
                    counts["packages"] += 1

            # Add scripts
            if "scripts" in item:
                for scr in item["scripts"]:
                    script = InitramfsScript(
                        id=str(uuid4()),
                        initramfs_profile_id=profile_id,
                        script_name=scr["script_name"],
                        script_type=scr["script_type"],
                        content=scr["content"],
                        execution_order=scr.get("execution_order", 50),
                        required=scr.get("required", True),
                        metadata_json=scr.get("metadata"),
                    )
                    session.add(script)
                    counts["scripts"] += 1

            # Add hooks
            if "hooks" in item:
                for hook_item in item["hooks"]:
                    hook = InitramfsHook(
                        id=str(uuid4()),
                        initramfs_profile_id=profile_id,
                        hook_name=hook_item["hook_name"],
                        hook_stage=hook_item["hook_stage"],
                        command=hook_item["command"],
                        execution_order=hook_item.get("execution_order", 50),
                        enabled=hook_item.get("enabled", True),
                        metadata_json=hook_item.get("metadata"),
                    )
                    session.add(hook)
                    counts["hooks"] += 1

    if any(counts.values()):
        session.flush()

    return counts


# ---------------------------------------------------------------------------
# M49 — Update / OTA / Recovery seed data
# ---------------------------------------------------------------------------

UPDATE_STRATEGY_KINDS: list[tuple[str, str, str, int]] = [
    (
        "full",
        "Full Image Update",
        "Replace the entire OS image in a single atomic write. Simplest and most reliable; "
        "requires A/B partitions or temporary storage for zero-downtime.",
        0,
    ),
    (
        "a-b",
        "A/B Partition Update",
        "Maintain two OS slots (A and B). Apply the new image to the inactive slot while "
        "the device runs from the active slot, then switch boot targets on the next reboot.",
        1,
    ),
    (
        "delta",
        "Delta / Incremental Update",
        "Compute and ship only the binary difference between the current and target image. "
        "Reduces bandwidth and update time; requires a delta-patch runtime on the device.",
        2,
    ),
    (
        "recovery",
        "Recovery-Boot Update",
        "Reboot into a minimal recovery environment that applies the update bundle and "
        "validates the result before handing control back to the main OS.",
        3,
    ),
    (
        "rollback",
        "Rollback / Generation Revert",
        "Revert the active OS slot to the previous known-good generation. Useful after a "
        "failed update or user-initiated downgrade; requires generation tracking.",
        4,
    ),
    (
        "manual",
        "Manual / Out-of-Band Update",
        "No automatic update mechanism. Updates are applied by an operator via CLI or "
        "external tooling. Suitable for air-gapped or tightly controlled environments.",
        5,
    ),
]


def seed_update_strategy_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(
            select(UpdateStrategyKind.kind)
        ).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in UPDATE_STRATEGY_KINDS:
        if kind in existing:
            continue
        session.add(
            UpdateStrategyKind(
                kind=kind,
                label=label,
                description=description,
                display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M50 — SDK / dev-shell export kinds
# ---------------------------------------------------------------------------

SDK_EXPORT_KINDS = [
    (
        "pip",
        "Pip / venv",
        "Python virtual-environment export: requirements.txt + activate script.",
        0,
    ),
    (
        "conda",
        "Conda",
        "Conda environment export: environment.yml with pinned dependencies.",
        1,
    ),
    (
        "nix",
        "Nix Shell",
        "Nix shell expression (shell.nix / flake.nix) for reproducible dev shells.",
        2,
    ),
    (
        "shell-env",
        "Shell Env",
        "Bash/Zsh eval-able script that exports CROSS_COMPILE, ARCH, SYSROOT and "
        "toolchain PATH additions.",
        3,
    ),
    (
        "docker",
        "Docker Dev Container",
        "Dockerfile + .devcontainer.json for VS Code Remote Containers / Codespaces.",
        4,
    ),
]


def seed_sdk_export_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(SDKExportKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in SDK_EXPORT_KINDS:
        if kind in existing:
            continue
        session.add(
            SDKExportKind(
                kind=kind,
                label=label,
                description=description,
                display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M51 — Cache / Mirror / Offline policy kinds
# ---------------------------------------------------------------------------

CACHE_POLICY_KINDS = [
    (
        "always",
        "Always Cache",
        "Always write the fetch result to the local cache, even if already present.",
        0,
    ),
    (
        "prefer",
        "Prefer Cache",
        "Use the local cache when available; fetch and store on cache miss.",
        1,
    ),
    (
        "bypass",
        "Bypass Cache",
        "Never use or write to the local cache; always re-fetch from upstream.",
        2,
    ),
    (
        "offline-only",
        "Offline Only",
        "Serve exclusively from local cache; fail hard if the artefact is not cached.",
        3,
    ),
]


def seed_cache_policy_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(CachePolicyKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in CACHE_POLICY_KINDS:
        if kind in existing:
            continue
        session.add(
            CachePolicyKind(
                kind=kind,
                label=label,
                description=description,
                display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M53 — Hardware probe source kinds
# ---------------------------------------------------------------------------

PROBE_SOURCE_KINDS = [
    ("udev", "udev / sysfs", "Linux udev device database and sysfs attributes.", 0),
    ("dmidecode", "DMI Decode", "BIOS/UEFI DMI table dump via dmidecode.", 1),
    ("lshw", "lshw", "Hardware lister (lshw -json) full device tree.", 2),
    ("sysfs", "sysfs only", "Direct sysfs attribute reads without udev.", 3),
    ("manual", "Manual JSON", "Hand-crafted JSON probe record entered by operator.", 4),
]


def seed_probe_source_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(ProbeSourceKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in PROBE_SOURCE_KINDS:
        if kind in existing:
            continue
        session.add(
            ProbeSourceKind(
                kind=kind, label=label,
                description=description, display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M54 — Layer kinds
# ---------------------------------------------------------------------------

LAYER_KINDS = [
    ("base", "Base RootFS", "Minimal root filesystem — the immutable foundation layer.", 0),
    ("bsp", "BSP / Board", "Board-support package layer: kernel, firmware, device trees.", 1),
    ("extension", "Extension", "Optional feature extension overlaid on the base.", 2),
    ("app", "Application", "User-space application layer (GUI apps, daemons).", 3),
    ("compliance", "Compliance", "Audit/compliance artefacts, SBOM, licence notices.", 4),
    ("debug", "Debug", "Debug symbols, profiling tools, test infrastructure.", 5),
]


def seed_layer_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(LayerKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in LAYER_KINDS:
        if kind in existing:
            continue
        session.add(
            LayerKind(
                kind=kind, label=label,
                description=description, display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M55 — Override / masking action kinds
# ---------------------------------------------------------------------------

OVERRIDE_KINDS = [
    ("set", "Set", "Force the target key to the given value, replacing any existing value.", 0),
    ("unset", "Unset", "Remove/delete the target key entirely.", 1),
    ("mask", "Mask", "Mask the target (e.g. systemd unit mask — redirect to /dev/null).", 2),
    ("append", "Append", "Append the value to an existing list or multi-value field.", 3),
    ("prepend", "Prepend", "Prepend the value before existing entries.", 4),
    ("replace", "Replace (regex)", "Regex find-and-replace on the current value.", 5),
]


def seed_override_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(OverrideKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in OVERRIDE_KINDS:
        if kind in existing:
            continue
        session.add(
            OverrideKind(
                kind=kind, label=label,
                description=description, display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M56 — Patch Queue / Source Patch Manager
# ---------------------------------------------------------------------------

PATCH_TARGET_KINDS: list[tuple[str, str, str, int]] = [
    (
        "kernel",
        "Kernel Source",
        "Patches applied to kernel source tree before build.",
        10,
    ),
    (
        "package-source",
        "Package Source",
        "Patches applied to a package source tarball or VCS checkout.",
        20,
    ),
    (
        "branding",
        "Branding Assets",
        "Patches that overlay or replace branding files (icons, strings, splash).",
        30,
    ),
    (
        "config-template",
        "Config Template",
        "Patches applied to configuration templates before generation.",
        40,
    ),
    (
        "build-recipe",
        "Build Recipe",
        "Patches applied to build recipes (Makefile, CMakeLists, etc.).",
        50,
    ),
]


def seed_patch_target_kinds(session: "Session") -> int:
    existing = {
        row[0]
        for row in session.execute(select(PatchTargetKind.kind)).fetchall()
    }
    inserted = 0
    for kind, label, description, display_order in PATCH_TARGET_KINDS:
        if kind in existing:
            continue
        session.add(
            PatchTargetKind(
                kind=kind, label=label,
                description=description, display_order=display_order,
            )
        )
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M57 — Dependency Graph Viewer
# ---------------------------------------------------------------------------

GRAPH_KINDS: list[tuple[str, str, str, int]] = [
    ("package", "Package Dependency Graph",
     "Directed graph of package build/runtime/test dependencies.", 10),
    ("build", "Build Graph",
     "Dependencies between build jobs and produced artifacts.", 20),
    ("runtime", "Runtime Dependency Graph",
     "Runtime package dependencies resolved from the build plan.", 30),
    ("kernel", "Kernel Module Graph",
     "Kernel module and driver inclusion dependencies.", 40),
    ("service", "Service Dependency Graph",
     "Service ordering and dependency chains (systemd units).", 50),
    ("image", "Image Composition Graph",
     "Layers and artifacts composing the final image.", 60),
    ("layer", "Layer Composition Graph",
     "Layer overlay order and dependencies.", 70),
]


def seed_graph_kinds(session: "Session") -> int:
    existing = {row[0] for row in session.execute(select(GraphKind.kind)).fetchall()}
    inserted = 0
    for kind, label, description, display_order in GRAPH_KINDS:
        if kind in existing:
            continue
        session.add(GraphKind(kind=kind, label=label,
                              description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M58 — Explain / Why Engine
# ---------------------------------------------------------------------------

EXPLAIN_TRACE_KINDS: list[tuple[str, str, str, int]] = [
    ("profile-explicit", "Profile Explicit",
     "Package/config/service explicitly listed in the profile.", 10),
    ("group", "Package Group",
     "Included via package group membership.", 20),
    ("dependency", "Transitive Dependency",
     "Required by another included package (transitive).", 30),
    ("driver", "Hardware Driver",
     "Required by the board hardware profile or probe data.", 40),
    ("security", "Security Policy",
     "Enforced by a security/hardening rule or compliance profile.", 50),
    ("layer", "Layer Override",
     "Introduced or modified by a composition layer entry.", 60),
    ("override", "Explicit Override",
     "Added or modified by an override/masking rule.", 70),
]


def seed_explain_trace_kinds(session: "Session") -> int:
    existing = {row[0] for row in session.execute(select(ExplainTraceKind.kind)).fetchall()}
    inserted = 0
    for kind, label, description, display_order in EXPLAIN_TRACE_KINDS:
        if kind in existing:
            continue
        session.add(ExplainTraceKind(kind=kind, label=label,
                                     description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M59 — Build / Profile / Release Diff
# ---------------------------------------------------------------------------

DIFF_REPORT_KINDS: list[tuple[str, str, str, int]] = [
    ("package", "Package Set Diff",
     "Added, removed, or version-changed packages.", 10),
    ("kernel-config", "Kernel Config Diff",
     "Changed Kconfig options between two builds or profiles.", 20),
    ("service", "Service Diff",
     "Added, removed, or changed service units.", 30),
    ("filesystem", "Filesystem Diff",
     "Added, removed files and permission changes in the image.", 40),
    ("sbom", "SBOM Diff",
     "Changes in the software bill of materials.", 50),
    ("size", "Size Diff",
     "Image and per-package size changes.", 60),
    ("hash", "Artifact Hash Diff",
     "Changed artifact content hashes.", 70),
]


def seed_diff_report_kinds(session: "Session") -> int:
    existing = {row[0] for row in session.execute(select(DiffReportKind.kind)).fetchall()}
    inserted = 0
    for kind, label, description, display_order in DIFF_REPORT_KINDS:
        if kind in existing:
            continue
        session.add(DiffReportKind(kind=kind, label=label,
                                   description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


# ---------------------------------------------------------------------------
# M60 — System Generations / Rollback Designer
# ---------------------------------------------------------------------------

ROLLBACK_KINDS: list[tuple[str, str, str, int]] = [
    ("full", "Full Rollback",
     "Roll back all components to the target generation state.", 10),
    ("partial", "Partial Rollback",
     "Roll back only changed packages, preserving user data.", 20),
    ("config-only", "Config-Only Rollback",
     "Roll back configuration files only, keep binaries.", 30),
    ("data-preserve", "Data-Preserving Rollback",
     "Full rollback but preserve /home and /var/data.", 40),
]


def seed_rollback_kinds(session: "Session") -> int:
    existing = {row[0] for row in session.execute(select(RollbackKind.kind)).fetchall()}
    inserted = 0
    for kind, label, description, display_order in ROLLBACK_KINDS:
        if kind in existing:
            continue
        session.add(RollbackKind(kind=kind, label=label,
                                 description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted

# ---------------------------------------------------------------------------
# M63 — Importers
# ---------------------------------------------------------------------------

from osfabricum.db.models import ImportKind, SizeBudgetKind, ReleaseChannel

IMPORT_KINDS: list[tuple[str, str, str, int]] = [
    ("buildroot", "Buildroot .config", "Import from Buildroot minimal .config", 10),
    ("openwrt", "OpenWrt .config", "Import from OpenWrt .config (UCI/feeds)", 20),
    ("yocto", "Yocto Layer Metadata", "Import from Yocto/OE layer.conf + recipes", 30),
    ("debian", "Debian Package List", "Import from debian/control or dpkg --get-selections", 40),
    ("alpine", "Alpine Package List", "Import from Alpine world file or APKBUILD", 50),
    ("nixos", "NixOS Configuration", "Import from NixOS configuration.nix", 60),
    ("rootfs", "Existing Rootfs", "Import by scanning an existing rootfs directory", 70),
    ("image", "Existing Image", "Import by scanning a mounted disk image", 80),
    ("kconfig", "Kernel .config", "Import kernel configuration from .config file", 90),
]

SIZE_BUDGET_KINDS: list[tuple[str, str, str, int]] = [
    ("image", "Image Total", "Total compressed image file size", 10),
    ("rootfs", "Rootfs Unpacked", "Total unpacked rootfs size on disk", 20),
    ("package-set", "Package Set", "Combined installed package footprint", 30),
    ("kernel", "Kernel + Modules", "vmlinuz + installed kernel module size", 40),
    ("initramfs", "Initramfs", "Compressed initramfs size", 50),
    ("apps", "Applications", "User-space application bundle size", 60),
]

RELEASE_CHANNELS: list[tuple[str, str, str, int]] = [
    ("stable", "Stable", "Production-ready releases", 10),
    ("testing", "Testing", "Release candidates and beta builds", 20),
    ("nightly", "Nightly", "Automated nightly builds from main", 30),
    ("lts", "LTS", "Long-term support releases", 40),
    ("dev", "Dev", "Development snapshots — not for production", 50),
]


def seed_import_kinds(session: "Session") -> int:
    existing = {
        r for (r,) in session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(ImportKind.kind)
        ).all()
    }
    inserted = 0
    for kind, label, description, display_order in IMPORT_KINDS:
        if kind in existing:
            continue
        session.add(ImportKind(kind=kind, label=label,
                               description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def seed_size_budget_kinds(session: "Session") -> int:
    existing = {
        r for (r,) in session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(SizeBudgetKind.kind)
        ).all()
    }
    inserted = 0
    for kind, label, description, display_order in SIZE_BUDGET_KINDS:
        if kind in existing:
            continue
        session.add(SizeBudgetKind(kind=kind, label=label,
                                   description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def seed_release_channels(session: "Session") -> int:
    existing = {
        r for (r,) in session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(ReleaseChannel.channel)
        ).all()
    }
    inserted = 0
    for channel, label, description, display_order in RELEASE_CHANNELS:
        if channel in existing:
            continue
        session.add(ReleaseChannel(channel=channel, label=label,
                                   description=description, display_order=display_order))
        inserted += 1
    if inserted:
        session.flush()
    return inserted

# ---------------------------------------------------------------------------
# Phase 5 — Reference Distribution Catalog Loaders
# ---------------------------------------------------------------------------

from osfabricum.db.models import (
    Architecture,
    Toolchain,
    Kernel,
    Distribution,
    Package,
    PackageVersion,
    PackageGroup,
    PackageGroupMember,
    PackageSet,
    PackageSetMember,
    Profile,
)


def seed_architectures_from_yaml(session: "Session", yaml_path: Path | None = None) -> int:
    """Insert architectures from catalog/seed/architectures.yaml (idempotent)."""
    if yaml_path is None:
        yaml_path = Path(__file__).parents[2] / "catalog" / "seed" / "architectures.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    existing = {a.name for a in session.scalars(select(Architecture)).all()}
    added = 0
    for item in (data or {}).get("items", []):
        name = item["name"]
        if name in existing:
            continue
        session.add(Architecture(id=str(uuid4()), name=name))
        existing.add(name)
        added += 1
    if added:
        session.flush()
    return added


def seed_boards_from_yaml(session: "Session", yaml_path: Path | None = None) -> int:
    """Insert boards from catalog/seed/boards.yaml (idempotent)."""
    if yaml_path is None:
        yaml_path = Path(__file__).parents[2] / "catalog" / "seed" / "boards.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    existing = {b.name for b in session.scalars(select(Board)).all()}
    added = 0
    for item in (data or {}).get("items", []):
        name = item["name"]
        if name in existing:
            continue
        arch_id = arch_map.get(item.get("arch", ""))
        if not arch_id:
            continue
        session.add(Board(
            id=str(uuid4()), name=name, arch_id=arch_id,
            boot_scheme=item.get("boot_scheme", "direct-kernel"),
            firmware_required=item.get("firmware_required", False),
            metadata_json=item.get("metadata"),
        ))
        existing.add(name)
        added += 1
    if added:
        session.flush()
    return added


def seed_toolchains_from_yaml(session: "Session", yaml_path: Path | None = None) -> int:
    """Insert toolchains from catalog/seed/toolchains.yaml (idempotent)."""
    if yaml_path is None:
        yaml_path = Path(__file__).parents[2] / "catalog" / "seed" / "toolchains.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    existing = {t.name for t in session.scalars(select(Toolchain)).all()}
    added = 0
    for item in (data or {}).get("items", []):
        name = item["name"]
        if name in existing:
            continue
        arch_id = arch_map.get(item.get("arch", ""))
        if not arch_id:
            continue
        session.add(Toolchain(
            id=str(uuid4()), name=name, arch_id=arch_id,
            libc=item.get("libc", "musl"),
            version=item.get("version", ""),
            source_type=item.get("source_type", "bootlin-prebuilt"),
            metadata_json=item.get("metadata"),
        ))
        existing.add(name)
        added += 1
    if added:
        session.flush()
    return added


def seed_kernels_from_yaml(session: "Session", yaml_path: Path | None = None) -> int:
    """Insert kernels from catalog/seed/kernels.yaml (idempotent)."""
    if yaml_path is None:
        yaml_path = Path(__file__).parents[2] / "catalog" / "seed" / "kernels.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    board_map = {b.name: b.id for b in session.scalars(select(Board)).all()}
    existing = {
        (k.name, k.version, k.arch_id)
        for k in session.scalars(select(Kernel)).all()
    }
    added = 0
    for item in (data or {}).get("items", []):
        arch_id = arch_map.get(item.get("arch", ""))
        if not arch_id:
            continue
        name = item["name"]
        version = item.get("version", "")
        key = (name, version, arch_id)
        if key in existing:
            continue
        board_id = board_map.get(item.get("board", ""))
        session.add(Kernel(
            id=str(uuid4()), name=name, version=version, arch_id=arch_id,
            board_id=board_id,
            source_uri=item.get("source_uri"),
            source_ref=item.get("source_ref"),
            metadata_json=item.get("metadata"),
        ))
        existing.add(key)
        added += 1
    if added:
        session.flush()
    return added


def seed_distributions_from_yaml(
    session: "Session",
    yaml_path: Path | None = None,
    class_name: str | None = None,
) -> int:
    """Insert distributions from catalog/seed/distributions.yaml (idempotent)."""
    if yaml_path is None:
        yaml_path = Path(__file__).parents[2] / "catalog" / "seed" / "distributions.yaml"
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        return 0
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    class_map = {
        c.name: c.id
        for c in session.scalars(select(DistributionClass)).all()
    }
    existing = {d.name for d in session.scalars(select(Distribution)).all()}
    added = 0
    for item in (data or {}).get("items", []):
        name = item["name"]
        if name in existing:
            continue
        cname = item.get("class", class_name)
        cid = class_map.get(cname) if cname else None
        session.add(Distribution(
            id=str(uuid4()), name=name,
            description=item.get("description"),
            default_channel=item.get("default_channel", "dev"),
            class_id=cid,
        ))
        existing.add(name)
        added += 1
    if added:
        session.flush()
    return added


def _get_or_create_package(session: "Session", name: str, kind: str = "system", layer: str = "system") -> "Package":
    """Get an existing package by name or create it (idempotent)."""
    pkg = session.scalars(select(Package).where(Package.name == name)).first()
    if pkg is None:
        pkg = Package(id=str(uuid4()), name=name, kind=kind, layer=layer)
        session.add(pkg)
        session.flush()
    return pkg


def _get_or_create_package_version(
    session: "Session", pkg: "Package", version: str, arch_id: str
) -> "PackageVersion":
    existing = session.scalars(
        select(PackageVersion).where(
            PackageVersion.package_id == pkg.id,
            PackageVersion.version == version,
            PackageVersion.arch_id == arch_id,
        )
    ).first()
    if existing is None:
        existing = PackageVersion(
            id=str(uuid4()), package_id=pkg.id,
            version=version, arch_id=arch_id, status="available",
        )
        session.add(existing)
        session.flush()
    return existing


def _get_or_create_package_group(
    session: "Session", name: str, dist_id: str, description: str = ""
) -> "PackageGroup":
    grp = session.scalars(
        select(PackageGroup).where(
            PackageGroup.distribution_id == dist_id,
            PackageGroup.name == name,
        )
    ).first()
    if grp is None:
        grp = PackageGroup(
            id=str(uuid4()), name=name,
            distribution_id=dist_id, description=description,
        )
        session.add(grp)
        session.flush()
    return grp


def _add_package_to_group(session: "Session", group: "PackageGroup", pkg: "Package") -> None:
    exists = session.scalars(
        select(PackageGroupMember).where(
            PackageGroupMember.group_id == group.id,
            PackageGroupMember.package_id == pkg.id,
        )
    ).first()
    if exists is None:
        session.add(PackageGroupMember(group_id=group.id, package_id=pkg.id))
        session.flush()


def _get_or_create_package_set(
    session: "Session", name: str, dist_id: str, description: str = ""
) -> "PackageSet":
    ps = session.scalars(
        select(PackageSet).where(
            PackageSet.distribution_id == dist_id,
            PackageSet.name == name,
        )
    ).first()
    if ps is None:
        ps = PackageSet(
            id=str(uuid4()), name=name,
            distribution_id=dist_id, description=description,
        )
        session.add(ps)
        session.flush()
    return ps


def _add_group_to_set(session: "Session", pset: "PackageSet", grp: "PackageGroup") -> None:
    exists = session.scalars(
        select(PackageSetMember).where(
            PackageSetMember.set_id == pset.id,
            PackageSetMember.member_kind == "group",
            PackageSetMember.group_id == grp.id,
        )
    ).first()
    if exists is None:
        session.add(PackageSetMember(
            id=str(uuid4()), set_id=pset.id,
            member_kind="group", group_id=grp.id,
        ))
        session.flush()


def _get_or_create_profile(
    session: "Session",
    name: str,
    dist_id: str,
    board_id: str | None,
    kernel_id: str | None,
    toolchain_id: str | None,
    package_set_id: str | None,
) -> "Profile":
    prof = session.scalars(
        select(Profile).where(
            Profile.distribution_id == dist_id,
            Profile.name == name,
        )
    ).first()
    if prof is None:
        prof = Profile(
            id=str(uuid4()), name=name, distribution_id=dist_id,
            board_id=board_id, kernel_id=kernel_id,
            toolchain_id=toolchain_id, package_set_id=package_set_id,
        )
        session.add(prof)
        session.flush()
    else:
        updated = False
        for attr, val in [
            ("board_id", board_id), ("kernel_id", kernel_id),
            ("toolchain_id", toolchain_id), ("package_set_id", package_set_id),
        ]:
            if val is not None and getattr(prof, attr) != val:
                setattr(prof, attr, val)
                updated = True
        if updated:
            session.flush()
    return prof


# ---------------------------------------------------------------------------
# M71 — TinyWifi Reference Distribution seed
# ---------------------------------------------------------------------------

TINYWIFI_PACKAGES: list[tuple[str, str, str]] = [
    # (name, kind, layer)
    ("busybox", "system", "base"),
    ("dropbear", "service", "services"),
    ("hostapd", "service", "services"),
    ("nanodhcp", "service", "services"),
    ("webui-agent", "service", "services"),
]

TINYWIFI_GROUPS: dict[str, list[str]] = {
    "tinywifi-base": ["busybox"],
    "tinywifi-networking": ["nanodhcp", "dropbear"],
    "tinywifi-wifi": ["hostapd"],
    "tinywifi-management": ["webui-agent"],
}


def seed_tinywifi_reference(session: "Session") -> dict[str, int]:
    """Seed TinyWifi reference distribution (M71). Idempotent."""
    from sqlalchemy import select

    # Ensure base catalog is present
    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    seed_toolchains_from_yaml(session)
    seed_kernels_from_yaml(session)
    seed_distribution_classes(session)

    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    board_map = {b.name: b.id for b in session.scalars(select(Board)).all()}
    kernel_map = {
        (k.name, k.version): k.id
        for k in session.scalars(select(Kernel)).all()
    }
    toolchain_map = {t.name: t.id for t in session.scalars(select(Toolchain)).all()}
    dist_map = {d.name: d.id for d in session.scalars(select(Distribution)).all()}
    class_map = {c.name: c.id for c in session.scalars(select(DistributionClass)).all()}

    counts: dict[str, int] = {"packages": 0, "groups": 0, "profiles": 0}

    # Distribution
    if "tinywifi" not in dist_map:
        d = Distribution(
            id=str(uuid4()), name="tinywifi",
            description="Minimal Wi-Fi access point OS",
            default_channel="dev",
            class_id=class_map.get("router"),
        )
        session.add(d)
        session.flush()
        dist_map["tinywifi"] = d.id
    dist_id = dist_map["tinywifi"]
    # Update class_id if not already set
    existing_dist = session.get(Distribution, dist_id)
    if existing_dist and existing_dist.class_id is None:
        existing_dist.class_id = class_map.get("router")
        session.flush()
    arch_id = arch_map.get("aarch64", "")

    # Packages
    pkg_map: dict[str, Package] = {}
    for name, kind, layer in TINYWIFI_PACKAGES:
        pkg = _get_or_create_package(session, name, kind, layer)
        pkg_map[name] = pkg
        _get_or_create_package_version(session, pkg, "latest", arch_id)
        counts["packages"] += 1

    # Package groups
    group_objs: dict[str, PackageGroup] = {}
    for gname, members in TINYWIFI_GROUPS.items():
        grp = _get_or_create_package_group(session, gname, dist_id, f"TinyWifi {gname} packages")
        for pname in members:
            if pname in pkg_map:
                _add_package_to_group(session, grp, pkg_map[pname])
        group_objs[gname] = grp
        counts["groups"] += 1

    # Package set
    pset = _get_or_create_package_set(session, "tinywifi-default", dist_id, "TinyWifi default package set")
    for grp in group_objs.values():
        _add_group_to_set(session, pset, grp)

    # Profile: default
    board_id = board_map.get("rpi-zero-2w")
    kernel_id = kernel_map.get(("linux-rpi", "6.6.y"))
    tc_id = toolchain_map.get("aarch64-linux-musl-bootlin")
    _get_or_create_profile(
        session, "default", dist_id,
        board_id=board_id, kernel_id=kernel_id,
        toolchain_id=tc_id, package_set_id=pset.id,
    )
    counts["profiles"] += 1
    session.flush()

    # Config values (M50) — default tinywifi settings, idempotent
    _seed_tinywifi_config_values(session, dist_id)

    # Service profile (M50) — all services enabled by default, idempotent
    _seed_tinywifi_service_profile(session, dist_id)

    return counts


def _seed_tinywifi_config_values(session: "Session", dist_id: str) -> None:
    """Seed default config key-value pairs for tinywifi. Idempotent."""
    from datetime import datetime, UTC  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from osfabricum.db.models import DistributionConfigValue  # noqa: PLC0415

    defaults = {
        "hostapd.ssid": "tinywifi",
        "hostapd.passphrase": "tinywifi123",
        "hostapd.channel": "6",
        "hostapd.interface": "wlan0",
        "nanodhcp.server_ip": "192.168.42.1",
        "nanodhcp.pool_start": "192.168.42.10",
        "nanodhcp.pool_end": "192.168.42.100",
        "nanodhcp.lease_time": "3600",
        "nanodhcp.interface": "wlan0",
        "tinywifi.listen": "0.0.0.0:80",
        "network.ap_iface": "wlan0",
        "network.ap_addr": "192.168.42.1",
        "network.ap_prefix": "24",
    }
    now = datetime.now(UTC).replace(tzinfo=None)
    existing = {
        r.key
        for r in session.scalars(
            select(DistributionConfigValue).where(
                DistributionConfigValue.distribution_id == dist_id
            )
        ).all()
    }
    for key, value in defaults.items():
        if key not in existing:
            session.add(DistributionConfigValue(
                id=str(uuid4()),
                distribution_id=dist_id,
                key=key,
                value=value,
                updated_at=now,
            ))
    session.flush()


def _seed_tinywifi_service_profile(session: "Session", dist_id: str) -> None:
    """Seed default service profile for tinywifi. Idempotent."""
    from datetime import datetime, UTC  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from osfabricum.db.models import ServiceEntry, ServiceProfile  # noqa: PLC0415

    now = datetime.now(UTC).replace(tzinfo=None)

    sp = session.scalar(
        select(ServiceProfile).where(ServiceProfile.distribution_id == dist_id)
    )
    if sp is None:
        sp = ServiceProfile(
            id=str(uuid4()),
            name="tinywifi-default",
            distribution_id=dist_id,
            init_system="busybox",
            description="Default TinyWifi service topology",
            created_at=now,
            updated_at=now,
        )
        session.add(sp)
        session.flush()

    # Services — name maps to S##name init script prefix (e.g. "hostapd" → S60hostapd)
    services = [
        ("network", "S40 — configure wlan0 static IP for AP mode"),
        ("hostapd", "S60 — WiFi access point daemon"),
        ("nanodhcp", "S70 — DHCP server for connected clients"),
        ("tinywifi-web", "S80 — tinyWiFi web management panel"),
    ]
    existing_svc = {
        e.name
        for e in session.scalars(
            select(ServiceEntry).where(ServiceEntry.profile_id == sp.id)
        ).all()
    }
    for svc_name, description in services:
        if svc_name not in existing_svc:
            session.add(ServiceEntry(
                id=str(uuid4()),
                profile_id=sp.id,
                name=svc_name,
                unit_type="service",
                description=description,
                is_enabled=True,
                is_masked=False,
                priority=100,
            ))
    session.flush()


# ---------------------------------------------------------------------------
# M72 — NetOS Reference Distribution seed
# ---------------------------------------------------------------------------

NETOS_PACKAGES: list[tuple[str, str, str]] = [
    ("busybox", "system", "base"),
    ("openssh", "service", "services"),
    ("nftables", "system", "system"),
    ("frr", "service", "services"),
    ("ovs-vswitchd", "service", "services"),
    ("ovsdb-server", "service", "services"),
    ("strongswan", "service", "services"),
    ("curl", "system", "system"),
    ("systemd", "system", "system"),
    ("python3", "runtime", "runtime"),
    ("netdata", "service", "services"),
]

NETOS_GROUPS: dict[str, list[str]] = {
    "netos-base": ["busybox", "systemd", "openssh", "curl"],
    "netos-network": ["nftables", "frr"],
    "netos-sdn": ["ovs-vswitchd", "ovsdb-server"],
    "netos-security": ["strongswan"],
    "netos-monitoring": ["netdata", "python3"],
}

NETOS_SETS: dict[str, list[str]] = {
    "netos-nervum": ["netos-base", "netos-network", "netos-security", "netos-monitoring"],
    "netos-testum": ["netos-base", "netos-network"],
    "netos-ovsdb": ["netos-base", "netos-network", "netos-sdn", "netos-security"],
}


def seed_netos_reference(session: "Session") -> dict[str, int]:
    """Seed NetOS reference distribution (M72). Idempotent."""
    from sqlalchemy import select

    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    seed_toolchains_from_yaml(session)
    seed_distribution_classes(session)

    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    board_map = {b.name: b.id for b in session.scalars(select(Board)).all()}
    toolchain_map = {t.name: t.id for t in session.scalars(select(Toolchain)).all()}
    dist_map = {d.name: d.id for d in session.scalars(select(Distribution)).all()}
    class_map = {c.name: c.id for c in session.scalars(select(DistributionClass)).all()}

    counts: dict[str, int] = {"packages": 0, "groups": 0, "sets": 0, "profiles": 0}

    # Distribution
    if "netos" not in dist_map:
        d = Distribution(
            id=str(uuid4()), name="netos",
            description="NetOS network operating system — infrastructure/SDN server class",
            default_channel="dev",
            class_id=class_map.get("server"),
        )
        session.add(d)
        session.flush()
        dist_map["netos"] = d.id
    dist_id = dist_map["netos"]
    existing_dist = session.get(Distribution, dist_id)
    if existing_dist and existing_dist.class_id is None:
        existing_dist.class_id = class_map.get("server")
        session.flush()
    arch_id = arch_map.get("x86_64", "")

    # Packages
    pkg_map: dict[str, Package] = {}
    for name, kind, layer in NETOS_PACKAGES:
        pkg = _get_or_create_package(session, name, kind, layer)
        pkg_map[name] = pkg
        _get_or_create_package_version(session, pkg, "latest", arch_id)
        counts["packages"] += 1

    # Groups
    group_objs: dict[str, PackageGroup] = {}
    for gname, members in NETOS_GROUPS.items():
        grp = _get_or_create_package_group(session, gname, dist_id, f"NetOS {gname} packages")
        for pname in members:
            if pname in pkg_map:
                _add_package_to_group(session, grp, pkg_map[pname])
        group_objs[gname] = grp
        counts["groups"] += 1

    # Package sets + profiles
    board_id = board_map.get("qemu-x86_64")
    tc_id = toolchain_map.get("x86_64-linux-musl-bootlin")
    for set_name, group_names in NETOS_SETS.items():
        profile_name = set_name.removeprefix("netos-")
        pset = _get_or_create_package_set(session, set_name, dist_id, f"NetOS {profile_name} package set")
        for gname in group_names:
            if gname in group_objs:
                _add_group_to_set(session, pset, group_objs[gname])
        _get_or_create_profile(
            session, profile_name, dist_id,
            board_id=board_id, kernel_id=None,
            toolchain_id=tc_id, package_set_id=pset.id,
        )
        counts["sets"] += 1
        counts["profiles"] += 1
    session.flush()
    return counts


# ---------------------------------------------------------------------------
# M73 — Ocultum Reference Distribution seed
# ---------------------------------------------------------------------------

OCULTUM_PACKAGES: list[tuple[str, str, str]] = [
    ("busybox", "system", "base"),
    ("systemd", "system", "system"),
    ("wayland", "desktop", "desktop"),
    ("weston", "desktop", "desktop"),
    ("pipewire", "service", "services"),
    ("modem-manager", "service", "services"),
    ("network-manager", "service", "services"),
    ("calls-app", "application", "applications"),
    ("contacts-app", "application", "applications"),
    ("messages-app", "application", "applications"),
    ("phosh", "desktop", "desktop"),
    ("glib2", "library", "runtime"),
    ("gtk4", "library", "desktop"),
    ("wireplumber", "service", "services"),
]

OCULTUM_GROUPS: dict[str, list[str]] = {
    "ocultum-base": ["busybox", "systemd", "glib2"],
    "ocultum-ui": ["wayland", "weston", "phosh", "gtk4"],
    "ocultum-audio": ["pipewire", "wireplumber"],
    "ocultum-telephony": ["modem-manager", "network-manager", "calls-app"],
    "ocultum-apps": ["contacts-app", "messages-app"],
}

OCULTUM_SETS: dict[str, list[str]] = {
    "ocultum-communicator": [
        "ocultum-base", "ocultum-ui", "ocultum-audio",
        "ocultum-telephony", "ocultum-apps",
    ],
    "ocultum-minimal": ["ocultum-base", "ocultum-ui"],
    "ocultum-dev": [
        "ocultum-base", "ocultum-ui", "ocultum-audio",
        "ocultum-telephony", "ocultum-apps",
    ],
}


def seed_ocultum_reference(session: "Session") -> dict[str, int]:
    """Seed Ocultum reference distribution (M73). Idempotent."""
    from sqlalchemy import select

    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    seed_toolchains_from_yaml(session)
    seed_distribution_classes(session)

    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    board_map = {b.name: b.id for b in session.scalars(select(Board)).all()}
    toolchain_map = {t.name: t.id for t in session.scalars(select(Toolchain)).all()}
    dist_map = {d.name: d.id for d in session.scalars(select(Distribution)).all()}
    class_map = {c.name: c.id for c in session.scalars(select(DistributionClass)).all()}

    counts: dict[str, int] = {"packages": 0, "groups": 0, "sets": 0, "profiles": 0}

    # Distribution
    if "ocultum" not in dist_map:
        d = Distribution(
            id=str(uuid4()), name="ocultum",
            description="Ocultum secure mobile OS — mobile/handheld class",
            default_channel="dev",
            class_id=class_map.get("mobile-handheld"),
        )
        session.add(d)
        session.flush()
        dist_map["ocultum"] = d.id
    dist_id = dist_map["ocultum"]
    existing_dist = session.get(Distribution, dist_id)
    if existing_dist and existing_dist.class_id is None:
        existing_dist.class_id = class_map.get("mobile-handheld")
        session.flush()
    arch_id = arch_map.get("aarch64", arch_map.get("x86_64", ""))

    # Packages
    pkg_map: dict[str, Package] = {}
    for name, kind, layer in OCULTUM_PACKAGES:
        pkg = _get_or_create_package(session, name, kind, layer)
        pkg_map[name] = pkg
        _get_or_create_package_version(session, pkg, "latest", arch_id)
        counts["packages"] += 1

    # Groups
    group_objs: dict[str, PackageGroup] = {}
    for gname, members in OCULTUM_GROUPS.items():
        grp = _get_or_create_package_group(session, gname, dist_id, f"Ocultum {gname} packages")
        for pname in members:
            if pname in pkg_map:
                _add_package_to_group(session, grp, pkg_map[pname])
        group_objs[gname] = grp
        counts["groups"] += 1

    # Sets + profiles
    board_id = board_map.get("qemu-x86_64")
    tc_id = toolchain_map.get("aarch64-linux-musl-bootlin")
    for set_name, group_names in OCULTUM_SETS.items():
        profile_name = set_name.removeprefix("ocultum-")
        pset = _get_or_create_package_set(session, set_name, dist_id, f"Ocultum {profile_name} package set")
        for gname in group_names:
            if gname in group_objs:
                _add_group_to_set(session, pset, group_objs[gname])
        _get_or_create_profile(
            session, profile_name, dist_id,
            board_id=board_id, kernel_id=None,
            toolchain_id=tc_id, package_set_id=pset.id,
        )
        counts["sets"] += 1
        counts["profiles"] += 1
    session.flush()
    return counts


# ---------------------------------------------------------------------------
# M74 — TinyDesk Reference Distribution seed
# ---------------------------------------------------------------------------

TINYDESK_PACKAGES: list[tuple[str, str, str]] = [
    # (name, kind, layer)
    ("busybox", "system", "base"),
    ("xterm", "application", "desktop"),
    ("openbox", "application", "desktop"),
    ("xorg-server", "system", "system"),
]

TINYDESK_GROUPS: dict[str, list[str]] = {
    "tinydesk-base": ["busybox"],
    "tinydesk-desktop": ["xterm", "openbox", "xorg-server"],
}


def seed_tinydesk_reference(session: "Session") -> dict[str, int]:
    """Seed TinyDesk reference distribution (M74). Idempotent.

    Minimal desktop distribution: BusyBox userland + Xorg + Openbox + xterm,
    targeting Orange Pi 5 (aarch64/RK3588S) hardware.
    """
    from sqlalchemy import select  # noqa: PLC0415

    seed_architectures_from_yaml(session)
    seed_boards_from_yaml(session)
    seed_toolchains_from_yaml(session)
    seed_kernels_from_yaml(session)
    seed_distribution_classes(session)

    arch_map = {a.name: a.id for a in session.scalars(select(Architecture)).all()}
    board_map = {b.name: b.id for b in session.scalars(select(Board)).all()}
    kernel_map = {
        (k.name, k.version): k.id
        for k in session.scalars(select(Kernel)).all()
    }
    toolchain_map = {t.name: t.id for t in session.scalars(select(Toolchain)).all()}
    dist_map = {d.name: d.id for d in session.scalars(select(Distribution)).all()}
    class_map = {c.name: c.id for c in session.scalars(select(DistributionClass)).all()}

    counts: dict[str, int] = {"packages": 0, "groups": 0, "profiles": 0}

    # Distribution
    if "tinydesk" not in dist_map:
        d = Distribution(
            id=str(uuid4()), name="tinydesk",
            description="Minimal desktop OS — Openbox + xterm on Orange Pi",
            default_channel="dev",
            class_id=class_map.get("desktop"),
        )
        session.add(d)
        session.flush()
        dist_map["tinydesk"] = d.id
    dist_id = dist_map["tinydesk"]
    existing_dist = session.get(Distribution, dist_id)
    if existing_dist and existing_dist.class_id is None:
        existing_dist.class_id = class_map.get("desktop")
        session.flush()
    arch_id = arch_map.get("aarch64", "")

    # Packages
    pkg_map: dict[str, Package] = {}
    for name, kind, layer in TINYDESK_PACKAGES:
        pkg = _get_or_create_package(session, name, kind, layer)
        pkg_map[name] = pkg
        _get_or_create_package_version(session, pkg, "latest", arch_id)
        counts["packages"] += 1

    # Package groups
    group_objs: dict[str, PackageGroup] = {}
    for gname, members in TINYDESK_GROUPS.items():
        grp = _get_or_create_package_group(session, gname, dist_id, f"TinyDesk {gname} packages")
        for pname in members:
            if pname in pkg_map:
                _add_package_to_group(session, grp, pkg_map[pname])
        group_objs[gname] = grp
        counts["groups"] += 1

    # Package set
    pset = _get_or_create_package_set(session, "tinydesk-default", dist_id, "TinyDesk default package set")
    for grp in group_objs.values():
        _add_group_to_set(session, pset, grp)

    # Profile: orange-pi-5
    board_id = board_map.get("orange-pi-5")
    if board_id is None:
        board_id = board_map.get("rpi-zero-2w")
    kernel_id = kernel_map.get(("linux-rpi", "6.6.y"))
    tc_id = toolchain_map.get("aarch64-linux-musl-bootlin")
    _get_or_create_profile(
        session, "orange-pi-5", dist_id,
        board_id=board_id, kernel_id=kernel_id,
        toolchain_id=tc_id, package_set_id=pset.id,
    )
    counts["profiles"] += 1
    session.flush()
    return counts
