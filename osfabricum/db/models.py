"""ORM models for all OSFabricum database tables (ROADMAP section 4).

Primary keys are UUID strings generated in Python.  JSON columns use
SQLAlchemy's ``JSON`` type, which maps to TEXT in SQLite and JSON in
PostgreSQL.  Foreign keys use ``String(36)`` matching the UUID PK type.
Relationships are intentionally omitted in M2 to keep the model minimal;
they will be added when query patterns require them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osfabricum.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Core Registry
# ---------------------------------------------------------------------------


class Architecture(Base):
    __tablename__ = "architectures"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    arch_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("architectures.id"), nullable=False
    )
    boot_scheme: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    firmware_required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


# ---------------------------------------------------------------------------
# Board / BSP Models (M30)
# ---------------------------------------------------------------------------


class SocFamily(Base):
    __tablename__ = "soc_families"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    vendor: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardRevision(Base):
    __tablename__ = "board_revisions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    revision: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    soc_family_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("soc_families.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardFirmware(Base):
    __tablename__ = "board_firmware"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    source_uri: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    expected_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    placement: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardDeviceTree(Base):
    __tablename__ = "board_device_trees"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    dtb_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    source_uri: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    expected_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    placement: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardDefaultKernel(Base):
    __tablename__ = "board_default_kernels"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    kernel_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=False
    )
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardDefaultToolchain(Base):
    __tablename__ = "board_default_toolchains"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    toolchain_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("toolchains.id"), nullable=False
    )
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardSupportedLayout(Base):
    __tablename__ = "board_supported_layouts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    layout_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("partition_layouts.id"), nullable=False
    )
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardFlashMethod(Base):
    __tablename__ = "board_flash_methods"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    method_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    command_template: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    requires_tools: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    device_pattern: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardTestMethod(Base):
    __tablename__ = "board_test_methods"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    method_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    test_command: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    requires_tools: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BoardProbeProfile(Base):
    __tablename__ = "board_probe_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=False, index=True
    )
    board_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("board_revisions.id"), nullable=True
    )
    probe_method: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    match_pattern: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    match_fields: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    confidence: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=100)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


# ---------------------------------------------------------------------------
# Boot Chain Models (M31)
# ---------------------------------------------------------------------------


class BootChain(Base):
    __tablename__ = "boot_chains"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    boot_scheme_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_schemes.id"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)

    # Navigation to this chain's templates/files (M31).
    templates: Mapped[list[BootChainTemplate]] = relationship(viewonly=True)
    files: Mapped[list[BootChainFile]] = relationship(viewonly=True)


class BootChainTemplate(Base):
    __tablename__ = "boot_chain_templates"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    boot_chain_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False, index=True
    )
    template_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    variables: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BootChainFile(Base):
    __tablename__ = "boot_chain_files"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    boot_chain_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content_template: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_chain_templates.id"), nullable=True
    )
    placement: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    permissions: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BootChainBinding(Base):
    __tablename__ = "boot_chain_bindings"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    boot_chain_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False, index=True
    )
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True, index=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=True, index=True
    )
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=100)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


# M32: Initramfs / Early Boot Designer models


class InitramfsProfile(Base):
    __tablename__ = "initramfs_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    profile_type: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    compression: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="zstd")
    size_limit_mb: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    include_modules: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    include_firmware: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    enable_debug_shell: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    enable_network: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    enable_encryption_unlock: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    enable_factory_reset: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class InitramfsPackage(Base):
    __tablename__ = "initramfs_packages"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    initramfs_profile_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("initramfs_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    package_name: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    version_constraint: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=100)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class InitramfsScript(Base):
    __tablename__ = "initramfs_scripts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    initramfs_profile_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("initramfs_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    script_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    script_type: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    execution_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=50, index=True)
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class InitramfsHook(Base):
    __tablename__ = "initramfs_hooks"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    initramfs_profile_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("initramfs_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hook_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    hook_stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    command: Mapped[str] = mapped_column(sa.Text, nullable=False)
    execution_order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class InitramfsArtifact(Base):
    __tablename__ = "initramfs_artifacts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    initramfs_profile_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("initramfs_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    board_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    kernel_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    compression: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    modules_manifest_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    build_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=datetime.utcnow
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class Distribution(Base):
    __tablename__ = "distributions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_channel: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="dev")
    # Universal OS Builder Model (M25): default distribution class.
    class_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distribution_classes.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    distribution_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    inherits_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=True
    )
    inputs_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    # --- Universal OS Builder Model (M25): profile-level selections. ---
    # All nullable: a profile may pin any of these, or leave it to inheritance /
    # the resolver (M27 wires them into resolution; M25 only models them).
    class_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distribution_classes.id"), nullable=True
    )
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True
    )
    kernel_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=True
    )
    toolchain_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("toolchains.id"), nullable=True
    )
    package_set_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("package_sets.id"), nullable=True
    )
    boot_scheme_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boot_schemes.id"), nullable=True
    )
    image_recipe_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=True
    )
    branding_profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("branding_profiles.id"), nullable=True
    )
    graphical_profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("graphical_profiles.id"), nullable=True
    )
    network_profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("network_profiles.id"), nullable=True
    )
    security_profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("security_profiles.id"), nullable=True
    )
    update_strategy_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("update_strategies.id"), nullable=True
    )
    validation_profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("validation_profiles.id"), nullable=True
    )

    __table_args__ = (sa.UniqueConstraint("distribution_id", "name", name="uq_profiles_dist_name"),)


class Kernel(Base):
    __tablename__ = "kernels"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    arch_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("architectures.id"), nullable=False
    )
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True
    )
    source_uri: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("name", "version", "arch_id", name="uq_kernels_name_ver_arch"),
    )


class KernelConfig(Base):
    __tablename__ = "kernel_configs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    kernel_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=False
    )
    board_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("boards.id"), nullable=False)
    config_artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )


class Toolchain(Base):
    __tablename__ = "toolchains"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    arch_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("architectures.id"), nullable=False
    )
    libc: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class ToolchainArtifact(Base):
    __tablename__ = "toolchain_artifacts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    toolchain_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("toolchains.id"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    namespace: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    package_type: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="native")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (sa.UniqueConstraint("name", "namespace", name="uq_packages_name_ns"),)


class PackageVersion(Base):
    __tablename__ = "package_versions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    package_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("packages.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    arch_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("architectures.id"), nullable=False
    )
    recipe_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("build_recipes.id", use_alter=True, name="fk_pkgver_recipe_id"),
        nullable=True,
    )
    artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="pending")

    __table_args__ = (
        sa.UniqueConstraint("package_id", "version", "arch_id", name="uq_pkgver_pkg_ver_arch"),
    )


class PackageDependency(Base):
    __tablename__ = "package_dependencies"

    src_version_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("package_versions.id"), primary_key=True
    )
    dep_name: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    dep_type: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    constraint_expr: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class BuildRecipe(Base):
    __tablename__ = "build_recipes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    package_version_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("package_versions.id"), nullable=True
    )
    build_system: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    steps_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    env_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    uri: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    expected_hash: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class Overlay(Base):
    __tablename__ = "overlays"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=True
    )
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    hook: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    content_artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    init_system: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    unit_artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    enabled_by_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)


class FirmwareBlob(Base):
    __tablename__ = "firmware_blobs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    board_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("boards.id"), nullable=False)
    filename: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    placement: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="boot")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (sa.UniqueConstraint("board_id", "filename", name="uq_firmware_board_file"),)


class PartitionLayout(Base):
    __tablename__ = "partition_layouts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True
    )
    layout_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class ConfigTemplate(Base):
    __tablename__ = "config_templates"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    template_artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class ConfigValue(Base):
    __tablename__ = "config_values"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("config_templates.id"), nullable=False
    )
    profile_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=True
    )
    board_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("boards.id"), nullable=True
    )
    values_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


# ---------------------------------------------------------------------------
# Build Runtime
# ---------------------------------------------------------------------------


class Artifact(Base):
    """Immutable content-addressed artifact in the store (ROADMAP section 5)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    arch: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    store_key: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    blob_sha256: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    media_type: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    retention_class: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="staging")
    pinned: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    producer_build_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)


class ArtifactRelation(Base):
    __tablename__ = "artifact_relations"

    parent_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), primary_key=True
    )
    child_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(sa.String(32), primary_key=True)


class ArtifactAttestation(Base):
    __tablename__ = "artifact_attestations"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    artifact_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=False
    )
    attestation_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    bundle_artifact_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True
    )


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    distribution_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=False
    )
    board_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("boards.id"), nullable=False)
    resolution_hash: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=_now, onupdate=_now
    )


class BuildJob(Base):
    __tablename__ = "build_jobs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    build_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("builds.id"), nullable=False)
    pyjobkit_job_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    step_kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="queued")


class BuildEvent(Base):
    __tablename__ = "build_events"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    build_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("builds.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("build_jobs.id"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)
    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class BuildLog(Base):
    __tablename__ = "build_logs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    build_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("builds.id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("build_jobs.id"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)
    stream: Mapped[str] = mapped_column(sa.String(8), nullable=False, default="stdout")
    line_no: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    hostname: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    kinds_json: Mapped[list[str] | None] = mapped_column(sa.JSON, nullable=True)
    tags_json: Mapped[list[str] | None] = mapped_column(sa.JSON, nullable=True)
    capabilities_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    distribution_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    channel: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="dev")
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "version", "channel", name="uq_releases_dvch"),
    )


class ReleaseArtifact(Base):
    __tablename__ = "release_artifacts"

    release_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("releases.id"), primary_key=True
    )
    artifact_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("artifacts.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="image")


# M4 — The job queue is managed by pyjobkit's SQLBackend (job_tasks table).
# The old custom Job model is removed; use pyjobkit.backends.sql.schema.JobTasks
# for direct SQL access when needed.


# ---------------------------------------------------------------------------
# Universal OS Builder Model (M25)
#
# These entities make OSFabricum able to express any OS class as data.  M25
# creates the tables and the profile/distribution reference columns; the
# designer milestones (M33/M34/M39/M40/M45/M47/M49/M52) flesh out the rich
# fields, and M27/M35/M55 wire them into the resolver.  ``distribution_id`` is
# nullable on the reusable entities: NULL means a global/shared definition
# usable across distributions; a value scopes it to one distribution.
# ---------------------------------------------------------------------------


class DistributionClass(Base):
    """A class of OS product (embedded, router, server, desktop, …)."""

    __tablename__ = "distribution_classes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(32), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class PackageGroup(Base):
    """A named, reusable bundle of packages (M35 adds kinds/layers/variants)."""

    __tablename__ = "package_groups"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_package_groups_dist_name"),
    )


class PackageGroupMember(Base):
    __tablename__ = "package_group_members"

    group_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("package_groups.id"), primary_key=True
    )
    package_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("packages.id"), primary_key=True
    )
    version_constraint: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class PackageSet(Base):
    """A selection of groups and/or packages attachable to a profile."""

    __tablename__ = "package_sets"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_package_sets_dist_name"),
    )


class PackageSetMember(Base):
    __tablename__ = "package_set_members"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    set_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("package_sets.id"), nullable=False
    )
    member_kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # group | package
    group_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("package_groups.id"), nullable=True
    )
    package_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("packages.id"), nullable=True
    )


class BootScheme(Base):
    """A boot strategy (direct-kernel, u-boot, grub, …); M30/M31 extended."""

    __tablename__ = "boot_schemes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # M30 extensions (nullable for backward compat with M25 seed data):
    boot_type: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, default="direct")
    requires_bootloader: Mapped[bool | None] = mapped_column(
        sa.Boolean, nullable=True, default=False
    )
    requires_firmware: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True, default=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class ImageRecipe(Base):
    """An output image definition (M34: formats/filesystems/layouts as data).

    The recipe is the hub: it ties a reusable :class:`PartitionLayout`, a
    :class:`SizePolicy` and a root :class:`FilesystemProfile` together, owns one
    or more :class:`ImageOutput` rows (multi-format per build) and any
    :class:`MountPolicy` / :class:`OverlayPolicy` entries. ``output_format``
    stays as the primary/default format for backward compatibility.
    """

    __tablename__ = "image_recipes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    output_format: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="raw")
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Plain id references (not DB-level FKs): these columns are added to an
    # existing table by migration 0010, and SQLite cannot DROP COLUMN a column
    # that participates in a foreign key — keeping them plain keeps downgrade
    # reversible. The service resolves them by explicit id lookup.
    partition_layout_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    size_policy_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    root_filesystem_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_image_recipes_dist_name"),
    )


class BrandingProfile(Base):
    """A branding/identity definition; M39 adds targets/assets."""

    __tablename__ = "branding_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_branding_profiles_dist_name"),
    )


class GraphicalProfile(Base):
    """A graphical-shell stack; M40 adds components/sessions."""

    __tablename__ = "graphical_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    mode: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="no-gui")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_graphical_profiles_dist_name"),
    )


class NetworkProfile(Base):
    """A networking definition; M45 adds interfaces/firewall/wifi."""

    __tablename__ = "network_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_network_profiles_dist_name"),
    )


class SecurityProfile(Base):
    """A hardening definition; M47 adds rules/sysctl/gates."""

    __tablename__ = "security_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_security_profiles_dist_name"),
    )


class UpdateStrategy(Base):
    """An update/OTA strategy; M49 adds manifests/rollback/recovery."""

    __tablename__ = "update_strategies"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    strategy: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="full-image")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_update_strategies_dist_name"),
    )


class ValidationProfile(Base):
    """A QA/validation definition; M52 adds checks/results/gates."""

    __tablename__ = "validation_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    distribution_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("distribution_id", "name", name="uq_validation_profiles_dist_name"),
    )


class BuildDraft(Base):
    """A saved, resumable Build Wizard session (M28).

    Carries the same shape as a ``POST /v1/plan`` request, so a draft is simply
    a plan request not yet submitted as a build.
    """

    __tablename__ = "build_drafts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    source_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="new")
    distribution: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    profile: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    board: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    overrides_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=_now, onupdate=_now
    )


class ProfileVersion(Base):
    """An immutable snapshot of a profile's full state (M27 versioning)."""

    __tablename__ = "profile_versions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("profiles.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)

    __table_args__ = (sa.UniqueConstraint("profile_id", "version", name="uq_profile_versions_pv"),)


# ---------------------------------------------------------------------------
# Kernel / Driver Designer (M33)
#
# Kconfig is modelled as a typed symbol graph — symbols carry a type and a
# prompt (hidden symbols have none), and dependencies are explicit edges
# (depends / select / imply) — so the resolver treats it as a dependency graph,
# never a flat list of checkboxes.
# ---------------------------------------------------------------------------


class KernelKconfigIndex(Base):
    """A Kconfig symbol index for one kernel source/version/arch."""

    __tablename__ = "kernel_kconfig_indexes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    kernel_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=False, index=True
    )
    arch: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)

    __table_args__ = (
        sa.UniqueConstraint("kernel_id", "arch", "source_ref", name="uq_kconfig_index"),
    )


class KernelOptionSymbol(Base):
    """A single Kconfig symbol (CONFIG_*). ``prompt`` NULL ⇒ not user-selectable."""

    __tablename__ = "kernel_option_symbols"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    index_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernel_kconfig_indexes.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    type: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # bool|tristate|string|int|hex
    prompt: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    help: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_value: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    depends_on: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # raw Kconfig expr
    choice_group: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (sa.UniqueConstraint("index_id", "name", name="uq_kconfig_symbol"),)


class KernelOptionDependency(Base):
    """A directed Kconfig edge: ``symbol`` (depends|select|imply) ``target``."""

    __tablename__ = "kernel_option_dependencies"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    symbol_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernel_option_symbols.id"), nullable=False, index=True
    )
    dep_kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # depends|select|imply
    target: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    condition: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class KernelConfigFragment(Base):
    """A named set of requested option values (a config layer)."""

    __tablename__ = "kernel_config_fragments"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    kernel_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)

    __table_args__ = (sa.UniqueConstraint("kernel_id", "name", name="uq_kconfig_fragment"),)


class KernelConfigValue(Base):
    __tablename__ = "kernel_config_values"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    fragment_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernel_config_fragments.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    value: Mapped[str] = mapped_column(sa.String(64), nullable=False)


class KernelConfigPreset(Base):
    """A saved, fully-resolved ``.config`` (with its content hash)."""

    __tablename__ = "kernel_config_presets"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    kernel_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)

    __table_args__ = (sa.UniqueConstraint("kernel_id", "name", name="uq_kconfig_preset"),)


class DriverBundle(Base):
    """A reusable hardware-driver bundle (kernel options + modules + firmware)."""

    __tablename__ = "driver_bundles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    kernel_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=_now)


class DriverBundleOption(Base):
    __tablename__ = "driver_bundle_kernel_options"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    bundle_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("driver_bundles.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    value: Mapped[str] = mapped_column(sa.String(8), nullable=False, default="y")  # y|m


class DriverBundleModule(Base):
    __tablename__ = "driver_bundle_modules"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    bundle_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("driver_bundles.id"), nullable=False, index=True
    )
    module_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)


class DriverBundleFirmware(Base):
    __tablename__ = "driver_bundle_firmware"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    bundle_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("driver_bundles.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)


class DriverBundleDtOverlay(Base):
    __tablename__ = "driver_bundle_dt_overlays"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    bundle_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("driver_bundles.id"), nullable=False, index=True
    )
    overlay_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)


class ExternalKernelModule(Base):
    """An out-of-tree kernel module (built against a specific kernel tree)."""

    __tablename__ = "external_kernel_modules"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class ExternalKernelModuleRecipe(Base):
    """How to build an external module against a particular kernel build tree."""

    __tablename__ = "external_kernel_module_recipes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    module_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("external_kernel_modules.id"), nullable=False, index=True
    )
    kernel_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("kernels.id"), nullable=False
    )
    build_system: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="kbuild")
    steps_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


# ---------------------------------------------------------------------------
# M34 — Filesystem / Image Recipe Designer (closes G-06)
# ---------------------------------------------------------------------------


class FilesystemProfile(Base):
    """A reusable filesystem definition (ext4, squashfs, erofs, btrfs, …)."""

    __tablename__ = "filesystem_profiles"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    fs_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    mount_point: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    read_only: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    compression: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    options_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)


class SizePolicy(Base):
    """A reusable image sizing policy (free space, alignment, reserve)."""

    __tablename__ = "size_policies"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    free_space_pct: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    min_free_mb: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    align_mb: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=4)
    reserve_mb: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    grow_to_fit: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)


class PartitionEntry(Base):
    """A partition within a :class:`PartitionLayout` (M34 normalizes layout_json)."""

    __tablename__ = "partition_entries"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    layout_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("partition_layouts.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    filesystem_id: Mapped[str | None] = mapped_column(
        sa.String(36), sa.ForeignKey("filesystem_profiles.id"), nullable=True
    )
    size_mb: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    grow: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    flags_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)

    __table_args__ = (sa.UniqueConstraint("layout_id", "name", name="uq_partition_entry_name"),)


class ImageOutput(Base):
    """One output format produced from an image recipe (multi-format per build)."""

    __tablename__ = "image_outputs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False, index=True
    )
    output_format: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    compression: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    filename_template: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    __table_args__ = (
        sa.UniqueConstraint("recipe_id", "output_format", name="uq_image_output_format"),
    )


class MountPolicy(Base):
    """An fstab-style mount entry attached to an image recipe."""

    __tablename__ = "mount_policies"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    target: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    fstype: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    options: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)


class OverlayPolicy(Base):
    """An overlayfs policy attached to an image recipe (RO root + RW overlay)."""

    __tablename__ = "overlay_policies"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    recipe_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False, index=True
    )
    target: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    lower_dir: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    upper_dir: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    work_dir: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    persistent: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
