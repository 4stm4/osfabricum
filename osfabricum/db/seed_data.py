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
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import yaml
from sqlalchemy import select

from osfabricum.db.models import (
    Board,
    BoardDeviceTree,
    BoardFirmware,
    BoardFlashMethod,
    BoardProbeProfile,
    BoardRevision,
    BoardTestMethod,
    BootScheme,
    DistributionClass,
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


# ---------------------------------------------------------------------------
# M30: BSP Seed Data Loaders
# ---------------------------------------------------------------------------

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
        
        session.add(SocFamily(
            id=str(uuid4()),
            name=item["name"],
            vendor=item.get("vendor"),
            description=item.get("description"),
            metadata_json=item.get("metadata"),
        ))
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
    existing = {
        (r.board_id, r.revision)
        for r in session.scalars(select(BoardRevision)).all()
    }
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
        
        session.add(BoardRevision(
            id=str(uuid4()),
            board_id=board_id,
            revision=revision,
            soc_family_id=soc_family_id,
            description=item.get("description"),
            is_default=item.get("is_default", False),
            metadata_json=item.get("metadata"),
        ))
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
        existing = {
            (f.board_id, f.filename)
            for f in session.scalars(select(BoardFirmware)).all()
        }
        for item in data["firmware"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            filename = item["filename"]
            
            if (board_id, filename) in existing:
                continue
            
            session.add(BoardFirmware(
                id=str(uuid4()),
                board_id=board_id,
                filename=filename,
                source_uri=item.get("source_uri"),
                source_ref=item.get("source_ref"),
                expected_hash=item.get("expected_hash"),
                required=item.get("required", True),
                placement=item.get("placement"),
                metadata_json=item.get("metadata"),
            ))
            counts["firmware"] += 1
    
    # Load device trees
    if "device_trees" in data:
        existing = {
            (d.board_id, d.filename)
            for d in session.scalars(select(BoardDeviceTree)).all()
        }
        for item in data["device_trees"]:
            board_name = item["board"]
            if board_name not in boards:
                continue
            board_id = boards[board_name]
            filename = item["filename"]
            
            if (board_id, filename) in existing:
                continue
            
            session.add(BoardDeviceTree(
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
            ))
            counts["device_trees"] += 1
    
    # Load flash methods
    if "flash_methods" in data:
        existing = {
            (m.board_id, m.method_name)
            for m in session.scalars(select(BoardFlashMethod)).all()
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
            session.add(BoardFlashMethod(
                id=str(uuid4()),
                board_id=board_id,
                method_name=method_name,
                description=item.get("description"),
                command_template=item.get("command_template"),
                requires_tools={"tools": requires_tools} if requires_tools else None,
                device_pattern=item.get("device_pattern"),
                is_default=item.get("is_default", False),
                metadata_json=item.get("metadata"),
            ))
            counts["flash_methods"] += 1
    
    # Load test methods
    if "test_methods" in data:
        existing = {
            (m.board_id, m.method_name)
            for m in session.scalars(select(BoardTestMethod)).all()
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
            session.add(BoardTestMethod(
                id=str(uuid4()),
                board_id=board_id,
                method_name=method_name,
                description=item.get("description"),
                test_command=item.get("test_command"),
                requires_tools={"tools": requires_tools} if requires_tools else None,
                timeout_seconds=item.get("timeout_seconds"),
                is_default=item.get("is_default", False),
                metadata_json=item.get("metadata"),
            ))
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
            
            session.add(BoardProbeProfile(
                id=str(uuid4()),
                board_id=board_id,
                probe_method=probe_method,
                match_pattern=item.get("match_pattern"),
                match_fields=item.get("match_fields"),
                confidence=item.get("confidence", 100),
                metadata_json=item.get("metadata"),
            ))
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
        existing_chains = {
            chain.id: chain
            for chain in session.scalars(select(BootChain)).all()
        }
        
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
