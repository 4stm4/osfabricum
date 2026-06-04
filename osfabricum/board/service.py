"""Board/BSP service layer (M30).

Provides CRUD operations for boards, SoC families, revisions, firmware,
device trees, flash methods, test methods, and probe profiles.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from osfabricum.db.models import (
    Board,
    BoardDeviceTree,
    BoardFirmware,
    BoardFlashMethod,
    BoardProbeProfile,
    BoardRevision,
    BoardTestMethod,
    SocFamily,
)
from osfabricum.db.session import sync_session as get_session


def create_soc_family(
    name: str,
    vendor: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new SoC family."""
    with get_session(db_url) as session:
        soc = SocFamily(
            id=str(uuid4()),
            name=name,
            vendor=vendor,
            description=description,
            metadata_json=metadata,
        )
        session.add(soc)
        session.commit()
        return _soc_family_to_dict(soc)


def list_soc_families(*, db_url: str | None = None) -> list[dict[str, Any]]:
    """List all SoC families."""
    with get_session(db_url) as session:
        stmt = select(SocFamily).order_by(SocFamily.name)
        socs = session.execute(stmt).scalars().all()
        return [_soc_family_to_dict(s) for s in socs]


def create_board_revision(
    board_id: str,
    revision: str,
    soc_family_id: str | None = None,
    description: str | None = None,
    is_default: bool = False,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new board revision."""
    with get_session(db_url) as session:
        # Verify board exists
        board = session.get(Board, board_id)
        if not board:
            raise ValueError(f"Board {board_id!r} not found")

        # Check for duplicate revision
        stmt = select(BoardRevision).where(
            BoardRevision.board_id == board_id,
            BoardRevision.revision == revision,
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            raise ValueError(f"Revision {revision!r} already exists for board {board_id!r}")

        rev = BoardRevision(
            id=str(uuid4()),
            board_id=board_id,
            revision=revision,
            soc_family_id=soc_family_id,
            description=description,
            is_default=is_default,
            metadata_json=metadata,
        )
        session.add(rev)
        session.commit()
        return _board_revision_to_dict(rev)


def list_board_revisions(board_id: str, *, db_url: str | None = None) -> list[dict[str, Any]]:
    """List all revisions for a board."""
    with get_session(db_url) as session:
        stmt = (
            select(BoardRevision)
            .where(BoardRevision.board_id == board_id)
            .order_by(BoardRevision.revision)
        )
        revisions = session.execute(stmt).scalars().all()
        return [_board_revision_to_dict(r) for r in revisions]


def add_board_firmware(
    board_id: str,
    filename: str,
    source_uri: str | None = None,
    source_ref: str | None = None,
    expected_hash: str | None = None,
    required: bool = True,
    placement: str | None = None,
    board_revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add firmware blob to a board."""
    with get_session(db_url) as session:
        firmware = BoardFirmware(
            id=str(uuid4()),
            board_id=board_id,
            board_revision_id=board_revision_id,
            filename=filename,
            source_uri=source_uri,
            source_ref=source_ref,
            expected_hash=expected_hash,
            required=required,
            placement=placement,
            metadata_json=metadata,
        )
        session.add(firmware)
        session.commit()
        return _board_firmware_to_dict(firmware)


def add_board_device_tree(
    board_id: str,
    filename: str,
    dtb_type: str,  # base or overlay
    source_uri: str | None = None,
    source_ref: str | None = None,
    expected_hash: str | None = None,
    required: bool = True,
    placement: str | None = None,
    board_revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add device tree to a board."""
    with get_session(db_url) as session:
        dtb = BoardDeviceTree(
            id=str(uuid4()),
            board_id=board_id,
            board_revision_id=board_revision_id,
            filename=filename,
            dtb_type=dtb_type,
            source_uri=source_uri,
            source_ref=source_ref,
            expected_hash=expected_hash,
            required=required,
            placement=placement,
            metadata_json=metadata,
        )
        session.add(dtb)
        session.commit()
        return _board_device_tree_to_dict(dtb)


def add_board_flash_method(
    board_id: str,
    method_name: str,
    description: str | None = None,
    command_template: str | None = None,
    requires_tools: list[str] | None = None,
    device_pattern: str | None = None,
    is_default: bool = False,
    board_revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add flash method to a board."""
    with get_session(db_url) as session:
        method = BoardFlashMethod(
            id=str(uuid4()),
            board_id=board_id,
            board_revision_id=board_revision_id,
            method_name=method_name,
            description=description,
            command_template=command_template,
            requires_tools={"tools": requires_tools} if requires_tools else None,
            device_pattern=device_pattern,
            is_default=is_default,
            metadata_json=metadata,
        )
        session.add(method)
        session.commit()
        return _board_flash_method_to_dict(method)


def add_board_test_method(
    board_id: str,
    method_name: str,
    description: str | None = None,
    test_command: str | None = None,
    requires_tools: list[str] | None = None,
    timeout_seconds: int | None = None,
    is_default: bool = False,
    board_revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add test method to a board."""
    with get_session(db_url) as session:
        method = BoardTestMethod(
            id=str(uuid4()),
            board_id=board_id,
            board_revision_id=board_revision_id,
            method_name=method_name,
            description=description,
            test_command=test_command,
            requires_tools={"tools": requires_tools} if requires_tools else None,
            timeout_seconds=timeout_seconds,
            is_default=is_default,
            metadata_json=metadata,
        )
        session.add(method)
        session.commit()
        return _board_test_method_to_dict(method)


def add_board_probe_profile(
    board_id: str,
    probe_method: str,
    match_pattern: str | None = None,
    match_fields: dict[str, Any] | None = None,
    confidence: int = 100,
    board_revision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add probe profile to a board."""
    with get_session(db_url) as session:
        profile = BoardProbeProfile(
            id=str(uuid4()),
            board_id=board_id,
            board_revision_id=board_revision_id,
            probe_method=probe_method,
            match_pattern=match_pattern,
            match_fields=match_fields,
            confidence=confidence,
            metadata_json=metadata,
        )
        session.add(profile)
        session.commit()
        return _board_probe_profile_to_dict(profile)


def get_board_with_bsp(board_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Get board with all BSP data (revisions, firmware, DTBs, methods)."""
    with get_session(db_url) as session:
        board = session.get(Board, board_id)
        if not board:
            raise ValueError(f"Board {board_id!r} not found")

        # Get all BSP components
        revisions_stmt = select(BoardRevision).where(BoardRevision.board_id == board_id)
        revisions = session.execute(revisions_stmt).scalars().all()

        firmware_stmt = select(BoardFirmware).where(BoardFirmware.board_id == board_id)
        firmware = session.execute(firmware_stmt).scalars().all()

        dtb_stmt = select(BoardDeviceTree).where(BoardDeviceTree.board_id == board_id)
        dtbs = session.execute(dtb_stmt).scalars().all()

        flash_stmt = select(BoardFlashMethod).where(BoardFlashMethod.board_id == board_id)
        flash_methods = session.execute(flash_stmt).scalars().all()

        test_stmt = select(BoardTestMethod).where(BoardTestMethod.board_id == board_id)
        test_methods = session.execute(test_stmt).scalars().all()

        probe_stmt = select(BoardProbeProfile).where(BoardProbeProfile.board_id == board_id)
        probe_profiles = session.execute(probe_stmt).scalars().all()

        return {
            "id": board.id,
            "name": board.name,
            "arch_id": board.arch_id,
            "boot_scheme": board.boot_scheme,
            "firmware_required": board.firmware_required,
            "metadata": board.metadata_json,
            "revisions": [_board_revision_to_dict(r) for r in revisions],
            "firmware": [_board_firmware_to_dict(f) for f in firmware],
            "device_trees": [_board_device_tree_to_dict(d) for d in dtbs],
            "flash_methods": [_board_flash_method_to_dict(m) for m in flash_methods],
            "test_methods": [_board_test_method_to_dict(m) for m in test_methods],
            "probe_profiles": [_board_probe_profile_to_dict(p) for p in probe_profiles],
        }


# Helper functions to convert ORM objects to dicts


def _soc_family_to_dict(soc: SocFamily) -> dict[str, Any]:
    return {
        "id": soc.id,
        "name": soc.name,
        "vendor": soc.vendor,
        "description": soc.description,
        "metadata": soc.metadata_json,
    }


def _board_revision_to_dict(rev: BoardRevision) -> dict[str, Any]:
    return {
        "id": rev.id,
        "board_id": rev.board_id,
        "revision": rev.revision,
        "soc_family_id": rev.soc_family_id,
        "description": rev.description,
        "is_default": rev.is_default,
        "metadata": rev.metadata_json,
    }


def _board_firmware_to_dict(fw: BoardFirmware) -> dict[str, Any]:
    return {
        "id": fw.id,
        "board_id": fw.board_id,
        "board_revision_id": fw.board_revision_id,
        "filename": fw.filename,
        "artifact_id": fw.artifact_id,
        "source_uri": fw.source_uri,
        "source_ref": fw.source_ref,
        "expected_hash": fw.expected_hash,
        "required": fw.required,
        "placement": fw.placement,
        "metadata": fw.metadata_json,
    }


def _board_device_tree_to_dict(dtb: BoardDeviceTree) -> dict[str, Any]:
    return {
        "id": dtb.id,
        "board_id": dtb.board_id,
        "board_revision_id": dtb.board_revision_id,
        "filename": dtb.filename,
        "dtb_type": dtb.dtb_type,
        "artifact_id": dtb.artifact_id,
        "source_uri": dtb.source_uri,
        "source_ref": dtb.source_ref,
        "expected_hash": dtb.expected_hash,
        "required": dtb.required,
        "placement": dtb.placement,
        "metadata": dtb.metadata_json,
    }


def _board_flash_method_to_dict(method: BoardFlashMethod) -> dict[str, Any]:
    return {
        "id": method.id,
        "board_id": method.board_id,
        "board_revision_id": method.board_revision_id,
        "method_name": method.method_name,
        "description": method.description,
        "command_template": method.command_template,
        "requires_tools": method.requires_tools.get("tools") if method.requires_tools else None,
        "device_pattern": method.device_pattern,
        "is_default": method.is_default,
        "metadata": method.metadata_json,
    }


def _board_test_method_to_dict(method: BoardTestMethod) -> dict[str, Any]:
    return {
        "id": method.id,
        "board_id": method.board_id,
        "board_revision_id": method.board_revision_id,
        "method_name": method.method_name,
        "description": method.description,
        "test_command": method.test_command,
        "requires_tools": method.requires_tools.get("tools") if method.requires_tools else None,
        "timeout_seconds": method.timeout_seconds,
        "is_default": method.is_default,
        "metadata": method.metadata_json,
    }


def _board_probe_profile_to_dict(profile: BoardProbeProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "board_id": profile.board_id,
        "board_revision_id": profile.board_revision_id,
        "probe_method": profile.probe_method,
        "match_pattern": profile.match_pattern,
        "match_fields": profile.match_fields,
        "confidence": profile.confidence,
        "metadata": profile.metadata_json,
    }


# Made with Bob
