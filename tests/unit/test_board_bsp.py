"""Tests for Board/BSP designer (M30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from osfabricum import board as board_service
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.db.session import sync_session


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """Create a temporary test database."""
    url = f"sqlite:///{tmp_path / 'test_board.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def _seed_boards(db_url: str) -> None:
    """Seed test boards."""
    from osfabricum.db.session import sync_session

    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture, Board

        # Create architecture first
        arch = Architecture(id="arch-aarch64", name="aarch64")
        session.add(arch)
        session.flush()
        
        # Create boards
        session.add(Board(
            id="rpi4",
            name="Raspberry Pi 4",
            arch_id=arch.id,
            boot_scheme="uefi",
        ))
        session.add(Board(
            id="rpi3",
            name="Raspberry Pi 3",
            arch_id=arch.id,
            boot_scheme="uefi",
        ))
        session.commit()


def test_create_soc_family(db_url: str) -> None:
    """Test creating a SoC family."""
    result = board_service.create_soc_family(
        name="BCM2711",
        vendor="Broadcom",
        description="Raspberry Pi 4 SoC",
        metadata={"cores": 4, "arch": "ARM Cortex-A72"},
        db_url=db_url,
    )
    assert result["name"] == "BCM2711"
    assert result["vendor"] == "Broadcom"
    assert result["metadata"]["cores"] == 4


def test_list_soc_families(db_url: str) -> None:
    """Test listing SoC families."""
    board_service.create_soc_family(name="BCM2711", vendor="Broadcom", db_url=db_url)
    board_service.create_soc_family(name="BCM2837", vendor="Broadcom", db_url=db_url)
    
    families = board_service.list_soc_families(db_url=db_url)
    assert len(families) == 2
    assert families[0]["name"] == "BCM2711"
    assert families[1]["name"] == "BCM2837"


def test_create_board_revision(db_url: str, _seed_boards: None) -> None:
    """Test creating a board revision."""
    soc = board_service.create_soc_family(name="BCM2711", db_url=db_url)
    
    result = board_service.create_board_revision(
        board_id="rpi4",
        revision="1.4",
        soc_family_id=soc["id"],
        description="Rev 1.4 with 8GB RAM",
        is_default=True,
        metadata={"ram": "8GB"},
        db_url=db_url,
    )
    assert result["revision"] == "1.4"
    assert result["board_id"] == "rpi4"
    assert result["is_default"] is True
    assert result["metadata"]["ram"] == "8GB"


def test_list_board_revisions(db_url: str, _seed_boards: None) -> None:
    """Test listing board revisions."""
    board_service.create_board_revision(board_id="rpi4", revision="1.1", db_url=db_url)
    board_service.create_board_revision(board_id="rpi4", revision="1.4", is_default=True, db_url=db_url)
    
    revisions = board_service.list_board_revisions("rpi4", db_url=db_url)
    assert len(revisions) == 2
    assert revisions[0]["revision"] == "1.1"
    assert revisions[1]["revision"] == "1.4"
    assert revisions[1]["is_default"] is True


def test_add_board_firmware(db_url: str, _seed_boards: None) -> None:
    """Test adding firmware to a board."""
    result = board_service.add_board_firmware(
        board_id="rpi4",
        filename="start4.elf",
        source_uri="https://github.com/raspberrypi/firmware",
        source_ref="master",
        expected_hash="abc123",
        required=True,
        placement="/boot",
        metadata={"type": "bootloader"},
        db_url=db_url,
    )
    assert result["filename"] == "start4.elf"
    assert result["board_id"] == "rpi4"
    assert result["required"] is True
    assert result["placement"] == "/boot"


def test_add_board_device_tree(db_url: str, _seed_boards: None) -> None:
    """Test adding device tree to a board."""
    result = board_service.add_board_device_tree(
        board_id="rpi4",
        filename="bcm2711-rpi-4-b.dtb",
        dtb_type="base",
        source_uri="https://github.com/raspberrypi/linux",
        required=True,
        placement="/boot",
        metadata={"compatible": "raspberrypi,4-model-b"},
        db_url=db_url,
    )
    assert result["filename"] == "bcm2711-rpi-4-b.dtb"
    assert result["dtb_type"] == "base"
    assert result["board_id"] == "rpi4"


def test_add_board_flash_method(db_url: str, _seed_boards: None) -> None:
    """Test adding flash method to a board."""
    result = board_service.add_board_flash_method(
        board_id="rpi4",
        method_name="dd",
        description="Write image with dd",
        command_template="dd if={image} of={device} bs=4M status=progress",
        requires_tools=["dd"],
        device_pattern="/dev/sd*",
        is_default=True,
        metadata={"safe": False},
        db_url=db_url,
    )
    assert result["method_name"] == "dd"
    assert result["board_id"] == "rpi4"
    assert result["is_default"] is True
    assert "dd" in result["requires_tools"]


def test_add_board_test_method(db_url: str, _seed_boards: None) -> None:
    """Test adding test method to a board."""
    result = board_service.add_board_test_method(
        board_id="rpi4",
        method_name="qemu",
        description="Test with QEMU",
        test_command="qemu-system-aarch64 -M raspi4 -kernel {kernel}",
        requires_tools=["qemu-system-aarch64"],
        timeout_seconds=300,
        is_default=True,
        metadata={"emulated": True},
        db_url=db_url,
    )
    assert result["method_name"] == "qemu"
    assert result["timeout_seconds"] == 300
    assert result["is_default"] is True


def test_add_board_probe_profile(db_url: str, _seed_boards: None) -> None:
    """Test adding probe profile to a board."""
    result = board_service.add_board_probe_profile(
        board_id="rpi4",
        probe_method="device_tree",
        match_pattern="raspberrypi,4-model-b",
        match_fields={"model": "Raspberry Pi 4", "serial": "10000000*"},
        confidence=95,
        metadata={"source": "device-tree"},
        db_url=db_url,
    )
    assert result["probe_method"] == "device_tree"
    assert result["match_pattern"] == "raspberrypi,4-model-b"
    assert result["confidence"] == 95


def test_get_board_with_bsp(db_url: str, _seed_boards: None) -> None:
    """Test getting board with all BSP data."""
    # Create SoC family
    soc = board_service.create_soc_family(name="BCM2711", vendor="Broadcom", db_url=db_url)
    
    # Create revision
    rev = board_service.create_board_revision(
        board_id="rpi4",
        revision="1.4",
        soc_family_id=soc["id"],
        is_default=True,
        db_url=db_url,
    )
    
    # Add firmware
    board_service.add_board_firmware(
        board_id="rpi4",
        filename="start4.elf",
        board_revision_id=rev["id"],
        db_url=db_url,
    )
    
    # Add device tree
    board_service.add_board_device_tree(
        board_id="rpi4",
        filename="bcm2711-rpi-4-b.dtb",
        dtb_type="base",
        board_revision_id=rev["id"],
        db_url=db_url,
    )
    
    # Add flash method
    board_service.add_board_flash_method(
        board_id="rpi4",
        method_name="dd",
        is_default=True,
        db_url=db_url,
    )
    
    # Get full BSP data
    bsp = board_service.get_board_with_bsp("rpi4", db_url=db_url)
    
    assert bsp["id"] == "rpi4"
    assert bsp["name"] == "Raspberry Pi 4"
    assert len(bsp["revisions"]) == 1
    assert bsp["revisions"][0]["revision"] == "1.4"
    assert bsp["revisions"][0]["is_default"] is True
    assert len(bsp["firmware"]) == 1
    assert bsp["firmware"][0]["filename"] == "start4.elf"
    assert len(bsp["device_trees"]) == 1
    assert bsp["device_trees"][0]["filename"] == "bcm2711-rpi-4-b.dtb"
    assert len(bsp["flash_methods"]) == 1
    assert bsp["flash_methods"][0]["method_name"] == "dd"


def test_board_not_found(db_url: str) -> None:
    """Test error when board not found."""
    with pytest.raises(ValueError, match="Board .* not found"):
        board_service.get_board_with_bsp("nonexistent", db_url=db_url)


def test_create_revision_for_nonexistent_board(db_url: str) -> None:
    """Test error when creating revision for nonexistent board."""
    with pytest.raises(ValueError, match="Board .* not found"):
        board_service.create_board_revision(
            board_id="nonexistent",
            revision="1.0",
            db_url=db_url,
        )

# Made with Bob
