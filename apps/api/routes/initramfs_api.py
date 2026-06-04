"""Initramfs REST API endpoints (M32)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from osfabricum import initramfs as initramfs_service
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1/initramfs", tags=["initramfs"])


# Request/Response models


class CreateInitramfsProfileRequest(BaseModel):
    name: str = Field(..., description="Profile name")
    profile_type: str = Field(
        ..., description="Profile type (minimal, recovery, encrypted, network, debug)"
    )
    description: str | None = Field(None, description="Description")
    compression: str = Field("zstd", description="Compression algorithm")
    size_limit_mb: int | None = Field(None, description="Size limit in MB")
    include_modules: bool = Field(True, description="Include kernel modules")
    include_firmware: bool = Field(False, description="Include firmware files")
    enable_debug_shell: bool = Field(False, description="Enable debug shell")
    enable_network: bool = Field(False, description="Enable network support")
    enable_encryption_unlock: bool = Field(False, description="Enable encrypted root unlock")
    enable_factory_reset: bool = Field(False, description="Enable factory reset")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class AddPackageRequest(BaseModel):
    package_name: str = Field(..., description="Package name")
    version_constraint: str | None = Field(None, description="Version constraint")
    required: bool = Field(True, description="Is required")
    priority: int = Field(100, description="Priority")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class AddScriptRequest(BaseModel):
    script_name: str = Field(..., description="Script name")
    script_type: str = Field(..., description="Script type (init, mount, network, unlock)")
    content: str = Field(..., description="Script content")
    execution_order: int = Field(50, description="Execution order")
    required: bool = Field(True, description="Is required")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class AddHookRequest(BaseModel):
    hook_name: str = Field(..., description="Hook name")
    hook_stage: str = Field(
        ..., description="Hook stage (pre-build, post-build, pre-pack, post-pack)"
    )
    command: str = Field(..., description="Command to execute")
    execution_order: int = Field(50, description="Execution order")
    enabled: bool = Field(True, description="Is enabled")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class ResolveRequest(BaseModel):
    board_id: str | None = Field(None, description="Board ID")
    kernel_version: str | None = Field(None, description="Kernel version")


class CreateArtifactRequest(BaseModel):
    board_id: str | None = Field(None, description="Board ID")
    kernel_version: str | None = Field(None, description="Kernel version")
    artifact_id: str | None = Field(None, description="Artifact ID")
    size_bytes: int | None = Field(None, description="Size in bytes")
    compression: str | None = Field(None, description="Compression used")
    modules_manifest: dict[str, Any] | None = Field(None, description="Modules manifest")
    build_hash: str | None = Field(None, description="Build hash")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


# Endpoints


@router.post("/profiles", dependencies=[Depends(WriteAuthDep)])
def create_profile(req: CreateInitramfsProfileRequest) -> dict[str, Any]:
    """Create a new initramfs profile."""
    return initramfs_service.create_initramfs_profile(
        name=req.name,
        profile_type=req.profile_type,
        description=req.description,
        compression=req.compression,
        size_limit_mb=req.size_limit_mb,
        include_modules=req.include_modules,
        include_firmware=req.include_firmware,
        enable_debug_shell=req.enable_debug_shell,
        enable_network=req.enable_network,
        enable_encryption_unlock=req.enable_encryption_unlock,
        enable_factory_reset=req.enable_factory_reset,
        metadata=req.metadata,
    )


@router.get("/profiles")
def list_profiles(profile_type: str | None = None) -> list[dict[str, Any]]:
    """List all initramfs profiles."""
    return initramfs_service.list_initramfs_profiles(profile_type=profile_type)


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict[str, Any]:
    """Get initramfs profile with all components."""
    return initramfs_service.get_initramfs_profile(profile_id)


@router.post("/profiles/{profile_id}/packages", dependencies=[Depends(WriteAuthDep)])
def add_package(profile_id: str, req: AddPackageRequest) -> dict[str, Any]:
    """Add a package to an initramfs profile."""
    return initramfs_service.add_initramfs_package(
        initramfs_profile_id=profile_id,
        package_name=req.package_name,
        version_constraint=req.version_constraint,
        required=req.required,
        priority=req.priority,
        metadata=req.metadata,
    )


@router.post("/profiles/{profile_id}/scripts", dependencies=[Depends(WriteAuthDep)])
def add_script(profile_id: str, req: AddScriptRequest) -> dict[str, Any]:
    """Add a script to an initramfs profile."""
    return initramfs_service.add_initramfs_script(
        initramfs_profile_id=profile_id,
        script_name=req.script_name,
        script_type=req.script_type,
        content=req.content,
        execution_order=req.execution_order,
        required=req.required,
        metadata=req.metadata,
    )


@router.post("/profiles/{profile_id}/hooks", dependencies=[Depends(WriteAuthDep)])
def add_hook(profile_id: str, req: AddHookRequest) -> dict[str, Any]:
    """Add a build hook to an initramfs profile."""
    return initramfs_service.add_initramfs_hook(
        initramfs_profile_id=profile_id,
        hook_name=req.hook_name,
        hook_stage=req.hook_stage,
        command=req.command,
        execution_order=req.execution_order,
        enabled=req.enabled,
        metadata=req.metadata,
    )


@router.post("/profiles/{profile_id}/resolve")
def resolve_profile(profile_id: str, req: ResolveRequest) -> dict[str, Any]:
    """Resolve initramfs dependencies and generate build plan."""
    return initramfs_service.resolve_initramfs(
        profile_id=profile_id,
        board_id=req.board_id,
        kernel_version=req.kernel_version,
    )


@router.post("/profiles/{profile_id}/validate")
def validate_profile(profile_id: str) -> dict[str, Any]:
    """Validate initramfs profile configuration."""
    return initramfs_service.validate_initramfs_profile(profile_id)


@router.post("/profiles/{profile_id}/artifacts", dependencies=[Depends(WriteAuthDep)])
def create_artifact(profile_id: str, req: CreateArtifactRequest) -> dict[str, Any]:
    """Record a built initramfs artifact."""
    return initramfs_service.create_initramfs_artifact(
        initramfs_profile_id=profile_id,
        board_id=req.board_id,
        kernel_version=req.kernel_version,
        artifact_id=req.artifact_id,
        size_bytes=req.size_bytes,
        compression=req.compression,
        modules_manifest=req.modules_manifest,
        build_hash=req.build_hash,
        metadata=req.metadata,
    )


# Made with Bob
