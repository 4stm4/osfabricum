"""Tests for boot chain service layer (M31) - simplified unit tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from osfabricum.db.base import Base
from osfabricum.db.models import BootChain, BootChainFile, BootChainTemplate


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database for testing."""
    url = "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_create_boot_chain_model(db_session: Session) -> None:
    """Test creating a boot chain ORM model directly."""
    chain = BootChain(
        name="GRUB UEFI",
        boot_scheme_id="uefi",
        description="GRUB bootloader for UEFI systems",
        metadata_json='{"version": "2.06"}',
    )
    db_session.add(chain)
    db_session.commit()
    
    assert chain.id is not None
    assert chain.name == "GRUB UEFI"
    assert chain.boot_scheme_id == "uefi"
    assert chain.description == "GRUB bootloader for UEFI systems"


def test_boot_chain_with_template(db_session: Session) -> None:
    """Test boot chain with template."""
    chain = BootChain(
        name="GRUB UEFI",
        boot_scheme_id="uefi",
    )
    db_session.add(chain)
    db_session.flush()
    
    template = BootChainTemplate(
        boot_chain_id=chain.id,
        template_type="grub_cfg",
        content="set timeout=5\nset default=0",
        variables_json='{"timeout": 5}',
    )
    db_session.add(template)
    db_session.commit()
    
    assert template.id is not None
    assert template.boot_chain_id == chain.id
    assert template.template_type == "grub_cfg"


def test_boot_chain_with_file(db_session: Session) -> None:
    """Test boot chain with file."""
    chain = BootChain(
        name="GRUB UEFI",
        boot_scheme_id="uefi",
    )
    db_session.add(chain)
    db_session.flush()
    
    file = BootChainFile(
        boot_chain_id=chain.id,
        filename="grub.cfg",
        placement="/boot/grub",
        content_template="set timeout={{ timeout }}",
        required=True,
        permissions="0644",
    )
    db_session.add(file)
    db_session.commit()
    
    assert file.id is not None
    assert file.boot_chain_id == chain.id
    assert file.filename == "grub.cfg"
    assert file.placement == "/boot/grub"
    assert file.required is True


def test_boot_chain_relationships(db_session: Session) -> None:
    """Test boot chain with templates and files relationships."""
    chain = BootChain(
        name="GRUB UEFI",
        boot_scheme_id="uefi",
    )
    db_session.add(chain)
    db_session.flush()
    
    # Add template
    template = BootChainTemplate(
        boot_chain_id=chain.id,
        template_type="grub_cfg",
        content="set timeout=5",
    )
    db_session.add(template)
    
    # Add file
    file = BootChainFile(
        boot_chain_id=chain.id,
        filename="grub.cfg",
        placement="/boot/grub",
        required=True,
    )
    db_session.add(file)
    db_session.commit()
    
    # Refresh to load relationships
    db_session.refresh(chain)
    
    assert len(chain.templates) == 1
    assert len(chain.files) == 1
    assert chain.templates[0].template_type == "grub_cfg"
    assert chain.files[0].filename == "grub.cfg"


def test_multiple_boot_chains(db_session: Session) -> None:
    """Test creating multiple boot chains."""
    chain1 = BootChain(name="GRUB UEFI", boot_scheme_id="uefi")
    chain2 = BootChain(name="U-Boot", boot_scheme_id="uboot")
    
    db_session.add_all([chain1, chain2])
    db_session.commit()
    
    chains = db_session.query(BootChain).all()
    assert len(chains) == 2
    assert {c.name for c in chains} == {"GRUB UEFI", "U-Boot"}


def test_boot_chain_file_optional(db_session: Session) -> None:
    """Test optional boot chain file."""
    chain = BootChain(name="Test Chain", boot_scheme_id="test")
    db_session.add(chain)
    db_session.flush()
    
    # Required file
    required_file = BootChainFile(
        boot_chain_id=chain.id,
        filename="required.cfg",
        placement="/boot",
        required=True,
    )
    
    # Optional file
    optional_file = BootChainFile(
        boot_chain_id=chain.id,
        filename="optional.cfg",
        placement="/boot",
        required=False,
    )
    
    db_session.add_all([required_file, optional_file])
    db_session.commit()
    
    db_session.refresh(chain)
    assert len(chain.files) == 2
    
    required = [f for f in chain.files if f.required]
    optional = [f for f in chain.files if not f.required]
    
    assert len(required) == 1
    assert len(optional) == 1

# Made with Bob
