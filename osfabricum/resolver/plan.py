"""BuildPlan dataclasses for the M12 Resolver output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolchainRef:
    """Resolved toolchain for this build."""

    id: str
    name: str
    arch: str
    version: str
    artifact_id: str | None = None


@dataclass
class KernelRef:
    """Resolved kernel for this build."""

    id: str
    name: str
    version: str
    artifact_id: str | None = None  # KernelConfig.config_artifact_id


@dataclass
class PackageRef:
    """A package version included in this build plan."""

    name: str
    version: str
    arch: str
    status: str  # "built" | "pending" | "missing"
    artifact_id: str | None = None
    package_version_id: str = ""


@dataclass
class FirmwareRef:
    """A firmware blob required by the target board."""

    filename: str
    placement: str
    required: bool
    artifact_id: str | None = None


@dataclass
class OverlayRef:
    """An overlay included in this build plan."""

    name: str
    artifact_id: str | None = None


@dataclass
class ScriptRef:
    """A script attached to this build plan."""

    name: str
    hook: str
    artifact_id: str | None = None


@dataclass
class PartitionLayoutRef:
    """Partition layout for the target board."""

    id: str
    name: str
    layout_json: dict[str, Any] | None = None


@dataclass
class BuildPlan:
    """Full resolved build plan for a (distribution, profile, board) triple.

    This is the output of :func:`~osfabricum.resolver.resolver.resolve_plan`.
    It is not stored in the database directly; the ``resolution_hash`` is
    written to the ``builds.resolution_hash`` column.
    """

    distribution: str
    profile: str
    board: str
    arch: str
    resolution_hash: str

    # Entity IDs — populated by resolve_plan(), used by the Build Pipeline (M18)
    distribution_id: str = ""
    profile_id: str = ""
    board_id: str = ""
    arch_id: str = ""

    toolchain: ToolchainRef | None = None
    kernel: KernelRef | None = None
    packages: list[PackageRef] = field(default_factory=list)
    firmware: list[FirmwareRef] = field(default_factory=list)
    overlays: list[OverlayRef] = field(default_factory=list)
    scripts: list[ScriptRef] = field(default_factory=list)
    partition_layout: PartitionLayoutRef | None = None

    missing_artifacts: list[str] = field(default_factory=list)
    required_jobs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)
