"""Tests for initramfs seed data loader (M32)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from osfabricum.db.base import Base
from osfabricum.db.models import InitramfsHook, InitramfsPackage, InitramfsProfile, InitramfsScript
from osfabricum.db.seed_data import seed_initramfs_profiles


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database for testing."""
    url = "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_seed_initramfs_profiles_from_yaml(db_session: Session, tmp_path: Path) -> None:
    """Test loading initramfs profiles from YAML file."""
    yaml_content = """
initramfs_profiles:
  - id: test-minimal
    name: Test Minimal
    profile_type: minimal
    description: Test minimal initramfs
    compression: zstd
    include_modules: true
    include_firmware: false
    metadata:
      test: true
    packages:
      - package_name: busybox
        required: true
        priority: 100
    scripts:
      - script_name: init
        script_type: init
        content: "#!/bin/sh\\necho test"
        execution_order: 10
        required: true
    hooks:
      - hook_name: test-hook
        hook_stage: pre-build
        command: echo test
        execution_order: 50
        enabled: true
"""

    yaml_file = tmp_path / "initramfs_profiles.yaml"
    yaml_file.write_text(yaml_content)

    # Load seed data
    counts = seed_initramfs_profiles(db_session, yaml_file)
    db_session.commit()

    # Verify counts
    assert counts["profiles"] == 1
    assert counts["packages"] == 1
    assert counts["scripts"] == 1
    assert counts["hooks"] == 1

    # Verify profile was created
    profile = db_session.query(InitramfsProfile).filter_by(id="test-minimal").first()
    assert profile is not None
    assert profile.name == "Test Minimal"
    assert profile.profile_type == "minimal"
    assert profile.compression == "zstd"

    # Verify package was created
    packages = (
        db_session.query(InitramfsPackage).filter_by(initramfs_profile_id="test-minimal").all()
    )
    assert len(packages) == 1
    assert packages[0].package_name == "busybox"

    # Verify script was created
    scripts = db_session.query(InitramfsScript).filter_by(initramfs_profile_id="test-minimal").all()
    assert len(scripts) == 1
    assert scripts[0].script_name == "init"

    # Verify hook was created
    hooks = db_session.query(InitramfsHook).filter_by(initramfs_profile_id="test-minimal").all()
    assert len(hooks) == 1
    assert hooks[0].hook_name == "test-hook"


def test_seed_initramfs_idempotent(db_session: Session, tmp_path: Path) -> None:
    """Test that seed function is idempotent."""
    yaml_content = """
initramfs_profiles:
  - id: test-profile
    name: Test Profile
    profile_type: minimal
"""

    yaml_file = tmp_path / "initramfs_profiles.yaml"
    yaml_file.write_text(yaml_content)

    # Load once
    counts1 = seed_initramfs_profiles(db_session, yaml_file)
    db_session.commit()
    assert counts1["profiles"] == 1

    # Load again - should skip existing
    counts2 = seed_initramfs_profiles(db_session, yaml_file)
    db_session.commit()
    assert counts2["profiles"] == 0

    # Verify only one profile exists
    profiles = db_session.query(InitramfsProfile).all()
    assert len(profiles) == 1


def test_seed_initramfs_missing_file(db_session: Session, tmp_path: Path) -> None:
    """Test handling of missing YAML file."""
    missing_file = tmp_path / "nonexistent.yaml"

    counts = seed_initramfs_profiles(db_session, missing_file)

    # Should return zero counts without error
    assert counts["profiles"] == 0
    assert counts["packages"] == 0
    assert counts["scripts"] == 0
    assert counts["hooks"] == 0


def test_seed_multiple_profiles(db_session: Session, tmp_path: Path) -> None:
    """Test loading multiple initramfs profiles."""
    yaml_content = """
initramfs_profiles:
  - id: minimal
    name: Minimal
    profile_type: minimal
  - id: recovery
    name: Recovery
    profile_type: recovery
  - id: encrypted
    name: Encrypted
    profile_type: encrypted
"""

    yaml_file = tmp_path / "initramfs_profiles.yaml"
    yaml_file.write_text(yaml_content)

    counts = seed_initramfs_profiles(db_session, yaml_file)
    db_session.commit()

    assert counts["profiles"] == 3

    profiles = db_session.query(InitramfsProfile).all()
    assert len(profiles) == 3
    assert {p.name for p in profiles} == {"Minimal", "Recovery", "Encrypted"}


# Made with Bob
