"""Tests for boot chain seed data loader (M31)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from osfabricum.db.base import Base
from osfabricum.db.models import BootChain, BootChainBinding, BootChainFile, BootChainTemplate
from osfabricum.db.seed_data import seed_boot_chains


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database for testing."""
    url = "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_seed_boot_chains_from_yaml(db_session: Session, tmp_path: Path) -> None:
    """Test loading boot chains from YAML file."""
    # Create a minimal YAML file
    yaml_content = """
boot_chains:
  - id: test-grub-uefi
    name: Test GRUB UEFI
    boot_scheme_id: uefi
    description: Test boot chain
    metadata:
      version: "2.06"
    templates:
      - template_type: grub_cfg
        content: |
          set timeout={{ timeout }}
        variables:
          timeout: 5
    files:
      - filename: grub.cfg
        placement: /boot/grub
        content_template: grub_cfg
        required: true
        permissions: "0644"

boot_chain_bindings:
  - boot_chain_id: test-grub-uefi
    board_id: test-board
    is_default: true
    priority: 100
"""
    
    yaml_file = tmp_path / "boot_chains.yaml"
    yaml_file.write_text(yaml_content)
    
    # Load seed data
    counts = seed_boot_chains(db_session, yaml_file)
    db_session.commit()
    
    # Verify counts
    assert counts["boot_chains"] == 1
    assert counts["templates"] == 1
    assert counts["files"] == 1
    assert counts["bindings"] == 1
    
    # Verify boot chain was created
    chain = db_session.query(BootChain).filter_by(id="test-grub-uefi").first()
    assert chain is not None
    assert chain.name == "Test GRUB UEFI"
    assert chain.boot_scheme_id == "uefi"
    
    # Verify template was created
    templates = db_session.query(BootChainTemplate).filter_by(boot_chain_id="test-grub-uefi").all()
    assert len(templates) == 1
    assert templates[0].template_type == "grub_cfg"
    assert "timeout" in templates[0].content
    
    # Verify file was created
    files = db_session.query(BootChainFile).filter_by(boot_chain_id="test-grub-uefi").all()
    assert len(files) == 1
    assert files[0].filename == "grub.cfg"
    assert files[0].placement == "/boot/grub"
    assert files[0].required is True
    
    # Verify binding was created
    bindings = db_session.query(BootChainBinding).filter_by(boot_chain_id="test-grub-uefi").all()
    assert len(bindings) == 1
    assert bindings[0].board_id == "test-board"
    assert bindings[0].is_default is True


def test_seed_boot_chains_idempotent(db_session: Session, tmp_path: Path) -> None:
    """Test that seed function is idempotent (doesn't duplicate data)."""
    yaml_content = """
boot_chains:
  - id: test-chain
    name: Test Chain
    boot_scheme_id: uefi
"""
    
    yaml_file = tmp_path / "boot_chains.yaml"
    yaml_file.write_text(yaml_content)
    
    # Load once
    counts1 = seed_boot_chains(db_session, yaml_file)
    db_session.commit()
    assert counts1["boot_chains"] == 1
    
    # Load again - should skip existing
    counts2 = seed_boot_chains(db_session, yaml_file)
    db_session.commit()
    assert counts2["boot_chains"] == 0
    
    # Verify only one chain exists
    chains = db_session.query(BootChain).all()
    assert len(chains) == 1


def test_seed_boot_chains_missing_file(db_session: Session, tmp_path: Path) -> None:
    """Test handling of missing YAML file."""
    missing_file = tmp_path / "nonexistent.yaml"
    
    counts = seed_boot_chains(db_session, missing_file)
    
    # Should return zero counts without error
    assert counts["boot_chains"] == 0
    assert counts["templates"] == 0
    assert counts["files"] == 0
    assert counts["bindings"] == 0


def test_seed_boot_chains_multiple_chains(db_session: Session, tmp_path: Path) -> None:
    """Test loading multiple boot chains."""
    yaml_content = """
boot_chains:
  - id: chain1
    name: Chain 1
    boot_scheme_id: uefi
  - id: chain2
    name: Chain 2
    boot_scheme_id: bios
  - id: chain3
    name: Chain 3
    boot_scheme_id: uboot
"""
    
    yaml_file = tmp_path / "boot_chains.yaml"
    yaml_file.write_text(yaml_content)
    
    counts = seed_boot_chains(db_session, yaml_file)
    db_session.commit()
    
    assert counts["boot_chains"] == 3
    
    chains = db_session.query(BootChain).all()
    assert len(chains) == 3
    assert {c.name for c in chains} == {"Chain 1", "Chain 2", "Chain 3"}

# Made with Bob
