"""Tests for initramfs ORM models (M32)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from osfabricum.db.base import Base
from osfabricum.db.models import (
    InitramfsArtifact,
    InitramfsHook,
    InitramfsPackage,
    InitramfsProfile,
    InitramfsScript,
)


@pytest.fixture
def db_session() -> Session:
    """Create an in-memory SQLite database for testing."""
    url = "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_create_initramfs_profile(db_session: Session) -> None:
    """Test creating an initramfs profile."""
    profile = InitramfsProfile(
        name="Minimal Initramfs",
        profile_type="minimal",
        description="Minimal initramfs for fast boot",
        compression="zstd",
        include_modules=True,
        include_firmware=False,
    )
    db_session.add(profile)
    db_session.commit()

    assert profile.id is not None
    assert profile.name == "Minimal Initramfs"
    assert profile.profile_type == "minimal"
    assert profile.compression == "zstd"


def test_initramfs_with_packages(db_session: Session) -> None:
    """Test initramfs profile with packages."""
    profile = InitramfsProfile(
        name="Recovery Initramfs",
        profile_type="recovery",
    )
    db_session.add(profile)
    db_session.flush()

    # Add packages
    pkg1 = InitramfsPackage(
        initramfs_profile_id=profile.id,
        package_name="busybox",
        required=True,
        priority=100,
    )
    pkg2 = InitramfsPackage(
        initramfs_profile_id=profile.id,
        package_name="e2fsprogs",
        required=True,
        priority=90,
    )
    db_session.add_all([pkg1, pkg2])
    db_session.commit()

    # Query packages
    packages = db_session.query(InitramfsPackage).filter_by(initramfs_profile_id=profile.id).all()

    assert len(packages) == 2
    assert {p.package_name for p in packages} == {"busybox", "e2fsprogs"}


def test_initramfs_with_scripts(db_session: Session) -> None:
    """Test initramfs profile with scripts."""
    profile = InitramfsProfile(
        name="Network Boot",
        profile_type="network",
        enable_network=True,
    )
    db_session.add(profile)
    db_session.flush()

    # Add init script
    script = InitramfsScript(
        initramfs_profile_id=profile.id,
        script_name="init",
        script_type="init",
        content="#!/bin/sh\nexec /sbin/init",
        execution_order=10,
        required=True,
    )
    db_session.add(script)
    db_session.commit()

    # Query scripts
    scripts = db_session.query(InitramfsScript).filter_by(initramfs_profile_id=profile.id).all()

    assert len(scripts) == 1
    assert scripts[0].script_name == "init"
    assert scripts[0].script_type == "init"


def test_initramfs_with_hooks(db_session: Session) -> None:
    """Test initramfs profile with build hooks."""
    profile = InitramfsProfile(
        name="Custom Initramfs",
        profile_type="minimal",
    )
    db_session.add(profile)
    db_session.flush()

    # Add hooks
    hook1 = InitramfsHook(
        initramfs_profile_id=profile.id,
        hook_name="strip-binaries",
        hook_stage="pre-pack",
        command="find /tmp/initramfs -type f -executable -exec strip {} \\;",
        execution_order=50,
        enabled=True,
    )
    hook2 = InitramfsHook(
        initramfs_profile_id=profile.id,
        hook_name="verify-init",
        hook_stage="post-build",
        command="test -x /tmp/initramfs/init",
        execution_order=10,
        enabled=True,
    )
    db_session.add_all([hook1, hook2])
    db_session.commit()

    # Query hooks
    hooks = (
        db_session.query(InitramfsHook)
        .filter_by(initramfs_profile_id=profile.id)
        .order_by(InitramfsHook.execution_order)
        .all()
    )

    assert len(hooks) == 2
    assert hooks[0].hook_name == "verify-init"
    assert hooks[1].hook_name == "strip-binaries"


def test_initramfs_artifact(db_session: Session) -> None:
    """Test recording an initramfs artifact."""
    profile = InitramfsProfile(
        name="Test Profile",
        profile_type="minimal",
    )
    db_session.add(profile)
    db_session.flush()

    # Create artifact
    artifact = InitramfsArtifact(
        initramfs_profile_id=profile.id,
        board_id="rpi4",
        kernel_version="6.1.0",
        artifact_id="initramfs-rpi4-6.1.0.cpio.zst",
        size_bytes=5242880,
        compression="zstd",
        build_hash="abc123def456",
        modules_manifest_json={"modules": ["ext4", "usb_storage"]},
    )
    db_session.add(artifact)
    db_session.commit()

    assert artifact.id is not None
    assert artifact.board_id == "rpi4"
    assert artifact.size_bytes == 5242880
    assert artifact.compression == "zstd"


def test_multiple_profiles(db_session: Session) -> None:
    """Test creating multiple initramfs profiles."""
    profiles_data = [
        ("Minimal", "minimal", False, False),
        ("Recovery", "recovery", True, False),
        ("Encrypted", "encrypted", False, True),
        ("Network Boot", "network", True, False),
        ("Debug", "debug", True, False),
    ]

    for name, ptype, network, encryption in profiles_data:
        profile = InitramfsProfile(
            name=name,
            profile_type=ptype,
            enable_network=network,
            enable_encryption_unlock=encryption,
        )
        db_session.add(profile)

    db_session.commit()

    # Query all profiles
    profiles = db_session.query(InitramfsProfile).all()
    assert len(profiles) == 5

    # Query by type
    minimal = db_session.query(InitramfsProfile).filter_by(profile_type="minimal").all()
    assert len(minimal) == 1

    # Query with network enabled
    network_profiles = db_session.query(InitramfsProfile).filter_by(enable_network=True).all()
    assert len(network_profiles) == 3


def test_profile_features(db_session: Session) -> None:
    """Test initramfs profile feature flags."""
    profile = InitramfsProfile(
        name="Full Featured",
        profile_type="recovery",
        include_modules=True,
        include_firmware=True,
        enable_debug_shell=True,
        enable_network=True,
        enable_encryption_unlock=True,
        enable_factory_reset=True,
    )
    db_session.add(profile)
    db_session.commit()

    assert profile.include_modules is True
    assert profile.include_firmware is True
    assert profile.enable_debug_shell is True
    assert profile.enable_network is True
    assert profile.enable_encryption_unlock is True
    assert profile.enable_factory_reset is True


# Made with Bob
