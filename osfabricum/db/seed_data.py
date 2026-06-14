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
    MimeTypeDefinition,
    ThemeAssetKind,
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
