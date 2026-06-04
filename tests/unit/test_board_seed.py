"""Tests for Board/BSP seed data loaders (M30)."""

from __future__ import annotations

from pathlib import Path

import pytest

from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.db.seed_data import (
    seed_board_bsp_from_yaml,
    seed_board_revisions_from_yaml,
    seed_soc_families_from_yaml,
)
from osfabricum.db.session import sync_session


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """Create a temporary test database."""
    url = f"sqlite:///{tmp_path / 'test_seed.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def _seed_boards(db_url: str) -> None:
    """Seed test boards."""
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture, Board

        # Create architecture
        arch = Architecture(id="arch-aarch64", name="aarch64")
        session.add(arch)
        session.flush()
        
        # Create boards
        session.add(Board(
            id="rpi-zero-2w",
            name="Raspberry Pi Zero 2W",
            arch_id=arch.id,
            boot_scheme="rpi-firmware",
            firmware_required=True,
        ))
        session.add(Board(
            id="qemu-x86_64",
            name="QEMU x86_64",
            arch_id=arch.id,
            boot_scheme="qemu",
            firmware_required=False,
        ))
        session.commit()


def test_seed_soc_families(db_url: str, tmp_path: Path) -> None:
    """Test loading SoC families from YAML."""
    yaml_file = tmp_path / "soc_families.yaml"
    yaml_file.write_text("""
apiVersion: osfabricum/v1
kind: SocFamilyList
items:
  - name: BCM2710
    vendor: Broadcom
    description: ARM Cortex-A53 SoC
    metadata:
      cores: 4
  - name: BCM2711
    vendor: Broadcom
    description: ARM Cortex-A72 SoC
    metadata:
      cores: 4
""")
    
    with sync_session(db_url) as session:
        count = seed_soc_families_from_yaml(session, yaml_file)
        session.commit()
    
    assert count == 2
    
    # Verify data
    with sync_session(db_url) as session:
        from osfabricum.db.models import SocFamily
        from sqlalchemy import select
        
        families = session.scalars(select(SocFamily)).all()
        assert len(families) == 2
        assert families[0].name == "BCM2710"
        assert families[0].vendor == "Broadcom"
        assert families[0].metadata_json["cores"] == 4


def test_seed_soc_families_idempotent(db_url: str, tmp_path: Path) -> None:
    """Test that seeding is idempotent."""
    yaml_file = tmp_path / "soc_families.yaml"
    yaml_file.write_text("""
apiVersion: osfabricum/v1
kind: SocFamilyList
items:
  - name: BCM2710
    vendor: Broadcom
""")
    
    with sync_session(db_url) as session:
        count1 = seed_soc_families_from_yaml(session, yaml_file)
        session.commit()
    
    with sync_session(db_url) as session:
        count2 = seed_soc_families_from_yaml(session, yaml_file)
        session.commit()
    
    assert count1 == 1
    assert count2 == 0  # Already exists


def test_seed_board_revisions(db_url: str, _seed_boards: None, tmp_path: Path) -> None:
    """Test loading board revisions from YAML."""
    # First create SoC family
    with sync_session(db_url) as session:
        from osfabricum.db.models import SocFamily
        session.add(SocFamily(id="soc-bcm2710", name="BCM2710", vendor="Broadcom"))
        session.commit()
    
    yaml_file = tmp_path / "board_revisions.yaml"
    yaml_file.write_text("""
apiVersion: osfabricum/v1
kind: BoardRevisionList
items:
  - board: rpi-zero-2w
    revision: "1.0"
    soc_family: BCM2710
    description: Initial revision
    is_default: true
    metadata:
      ram: 512MB
""")
    
    with sync_session(db_url) as session:
        count = seed_board_revisions_from_yaml(session, yaml_file)
        session.commit()
    
    assert count == 1
    
    # Verify data
    with sync_session(db_url) as session:
        from osfabricum.db.models import BoardRevision
        from sqlalchemy import select
        
        revisions = session.scalars(select(BoardRevision)).all()
        assert len(revisions) == 1
        assert revisions[0].revision == "1.0"
        assert revisions[0].is_default is True
        assert revisions[0].metadata_json["ram"] == "512MB"


def test_seed_board_bsp(db_url: str, _seed_boards: None, tmp_path: Path) -> None:
    """Test loading board BSP data from YAML."""
    yaml_file = tmp_path / "board_bsp.yaml"
    yaml_file.write_text("""
apiVersion: osfabricum/v1
kind: BoardBSPList

firmware:
  - board: rpi-zero-2w
    filename: start4.elf
    source_uri: https://github.com/raspberrypi/firmware
    required: true
    placement: /boot

device_trees:
  - board: rpi-zero-2w
    filename: bcm2710-rpi-zero-2-w.dtb
    dtb_type: base
    required: true
    placement: /boot

flash_methods:
  - board: rpi-zero-2w
    method_name: dd
    description: Write with dd
    command_template: "dd if={image} of={device}"
    requires_tools:
      - dd
    is_default: true

test_methods:
  - board: qemu-x86_64
    method_name: qemu-x86_64
    description: Test with QEMU
    test_command: "qemu-system-x86_64 -m 2G {image}"
    requires_tools:
      - qemu-system-x86_64
    timeout_seconds: 300
    is_default: true

probe_profiles:
  - board: rpi-zero-2w
    probe_method: device_tree
    match_pattern: raspberrypi,model-zero-2-w
    confidence: 100
""")
    
    with sync_session(db_url) as session:
        counts = seed_board_bsp_from_yaml(session, yaml_file)
        session.commit()
    
    assert counts["firmware"] == 1
    assert counts["device_trees"] == 1
    assert counts["flash_methods"] == 1
    assert counts["test_methods"] == 1
    assert counts["probe_profiles"] == 1
    
    # Verify firmware
    with sync_session(db_url) as session:
        from osfabricum.db.models import BoardFirmware
        from sqlalchemy import select
        
        firmware = session.scalars(select(BoardFirmware)).all()
        assert len(firmware) == 1
        assert firmware[0].filename == "start4.elf"
        assert firmware[0].required is True


def test_seed_nonexistent_file(db_url: str, tmp_path: Path) -> None:
    """Test that seeding nonexistent file returns 0."""
    yaml_file = tmp_path / "nonexistent.yaml"
    
    with sync_session(db_url) as session:
        count = seed_soc_families_from_yaml(session, yaml_file)
    
    assert count == 0


def test_seed_empty_file(db_url: str, tmp_path: Path) -> None:
    """Test that seeding empty file returns 0."""
    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("")
    
    with sync_session(db_url) as session:
        count = seed_soc_families_from_yaml(session, yaml_file)
    
    assert count == 0

# Made with Bob
