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
from sqlalchemy.orm import Mapped, mapped_column

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


class Distribution(Base):
    __tablename__ = "distributions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_channel: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="dev")
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
