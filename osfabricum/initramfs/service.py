"""Initramfs service layer (M32)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select

from osfabricum.db.models import (
    InitramfsArtifact,
    InitramfsHook,
    InitramfsPackage,
    InitramfsProfile,
    InitramfsScript,
)
from osfabricum.db.session import sync_session

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_initramfs_profile(
    name: str,
    profile_type: str,
    description: str | None = None,
    compression: str = "zstd",
    size_limit_mb: int | None = None,
    include_modules: bool = True,
    include_firmware: bool = False,
    enable_debug_shell: bool = False,
    enable_network: bool = False,
    enable_encryption_unlock: bool = False,
    enable_factory_reset: bool = False,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Create a new initramfs profile."""
    if session is None:
        with sync_session(db_url) as sess:
            return create_initramfs_profile(
                name=name,
                profile_type=profile_type,
                description=description,
                compression=compression,
                size_limit_mb=size_limit_mb,
                include_modules=include_modules,
                include_firmware=include_firmware,
                enable_debug_shell=enable_debug_shell,
                enable_network=enable_network,
                enable_encryption_unlock=enable_encryption_unlock,
                enable_factory_reset=enable_factory_reset,
                metadata=metadata,
                session=sess,
            )

    profile = InitramfsProfile(
        id=str(uuid4()),
        name=name,
        profile_type=profile_type,
        description=description,
        compression=compression,
        size_limit_mb=size_limit_mb,
        include_modules=include_modules,
        include_firmware=include_firmware,
        enable_debug_shell=enable_debug_shell,
        enable_network=enable_network,
        enable_encryption_unlock=enable_encryption_unlock,
        enable_factory_reset=enable_factory_reset,
        metadata_json=metadata,
    )
    session.add(profile)
    session.flush()

    return {
        "id": profile.id,
        "name": profile.name,
        "profile_type": profile.profile_type,
        "description": profile.description,
        "compression": profile.compression,
        "size_limit_mb": profile.size_limit_mb,
        "include_modules": profile.include_modules,
        "include_firmware": profile.include_firmware,
        "enable_debug_shell": profile.enable_debug_shell,
        "enable_network": profile.enable_network,
        "enable_encryption_unlock": profile.enable_encryption_unlock,
        "enable_factory_reset": profile.enable_factory_reset,
        "metadata": profile.metadata_json,
    }


def list_initramfs_profiles(
    profile_type: str | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    """List all initramfs profiles."""
    if session is None:
        with sync_session(db_url) as sess:
            return list_initramfs_profiles(profile_type=profile_type, session=sess)

    stmt = select(InitramfsProfile)
    if profile_type:
        stmt = stmt.where(InitramfsProfile.profile_type == profile_type)

    profiles = session.scalars(stmt).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "profile_type": p.profile_type,
            "description": p.description,
            "compression": p.compression,
            "include_modules": p.include_modules,
            "include_firmware": p.include_firmware,
            "enable_debug_shell": p.enable_debug_shell,
            "enable_network": p.enable_network,
            "enable_encryption_unlock": p.enable_encryption_unlock,
            "enable_factory_reset": p.enable_factory_reset,
        }
        for p in profiles
    ]


def get_initramfs_profile(
    profile_id: str,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Get initramfs profile with all packages, scripts, and hooks."""
    if session is None:
        with sync_session(db_url) as sess:
            return get_initramfs_profile(profile_id, session=sess)

    profile = session.get(InitramfsProfile, profile_id)
    if not profile:
        raise ValueError(f"Initramfs profile not found: {profile_id}")

    # Get packages
    packages = session.scalars(
        select(InitramfsPackage).where(InitramfsPackage.initramfs_profile_id == profile_id)
    ).all()

    # Get scripts
    scripts = session.scalars(
        select(InitramfsScript).where(InitramfsScript.initramfs_profile_id == profile_id)
    ).all()

    # Get hooks
    hooks = session.scalars(
        select(InitramfsHook).where(InitramfsHook.initramfs_profile_id == profile_id)
    ).all()

    return {
        "id": profile.id,
        "name": profile.name,
        "profile_type": profile.profile_type,
        "description": profile.description,
        "compression": profile.compression,
        "size_limit_mb": profile.size_limit_mb,
        "include_modules": profile.include_modules,
        "include_firmware": profile.include_firmware,
        "enable_debug_shell": profile.enable_debug_shell,
        "enable_network": profile.enable_network,
        "enable_encryption_unlock": profile.enable_encryption_unlock,
        "enable_factory_reset": profile.enable_factory_reset,
        "metadata": profile.metadata_json,
        "packages": [
            {
                "id": pkg.id,
                "package_name": pkg.package_name,
                "version_constraint": pkg.version_constraint,
                "required": pkg.required,
                "priority": pkg.priority,
            }
            for pkg in packages
        ],
        "scripts": [
            {
                "id": scr.id,
                "script_name": scr.script_name,
                "script_type": scr.script_type,
                "execution_order": scr.execution_order,
                "required": scr.required,
            }
            for scr in scripts
        ],
        "hooks": [
            {
                "id": h.id,
                "hook_name": h.hook_name,
                "hook_stage": h.hook_stage,
                "execution_order": h.execution_order,
                "enabled": h.enabled,
            }
            for h in hooks
        ],
    }


def add_initramfs_package(
    initramfs_profile_id: str,
    package_name: str,
    version_constraint: str | None = None,
    required: bool = True,
    priority: int = 100,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Add a package to an initramfs profile."""
    if session is None:
        with sync_session(db_url) as sess:
            return add_initramfs_package(
                initramfs_profile_id=initramfs_profile_id,
                package_name=package_name,
                version_constraint=version_constraint,
                required=required,
                priority=priority,
                metadata=metadata,
                session=sess,
            )

    pkg = InitramfsPackage(
        id=str(uuid4()),
        initramfs_profile_id=initramfs_profile_id,
        package_name=package_name,
        version_constraint=version_constraint,
        required=required,
        priority=priority,
        metadata_json=metadata,
    )
    session.add(pkg)
    session.flush()

    return {
        "id": pkg.id,
        "initramfs_profile_id": pkg.initramfs_profile_id,
        "package_name": pkg.package_name,
        "version_constraint": pkg.version_constraint,
        "required": pkg.required,
        "priority": pkg.priority,
    }


def add_initramfs_script(
    initramfs_profile_id: str,
    script_name: str,
    script_type: str,
    content: str,
    execution_order: int = 50,
    required: bool = True,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Add a script to an initramfs profile."""
    if session is None:
        with sync_session(db_url) as sess:
            return add_initramfs_script(
                initramfs_profile_id=initramfs_profile_id,
                script_name=script_name,
                script_type=script_type,
                content=content,
                execution_order=execution_order,
                required=required,
                metadata=metadata,
                session=sess,
            )

    script = InitramfsScript(
        id=str(uuid4()),
        initramfs_profile_id=initramfs_profile_id,
        script_name=script_name,
        script_type=script_type,
        content=content,
        execution_order=execution_order,
        required=required,
        metadata_json=metadata,
    )
    session.add(script)
    session.flush()

    return {
        "id": script.id,
        "initramfs_profile_id": script.initramfs_profile_id,
        "script_name": script.script_name,
        "script_type": script.script_type,
        "execution_order": script.execution_order,
        "required": script.required,
    }


def add_initramfs_hook(
    initramfs_profile_id: str,
    hook_name: str,
    hook_stage: str,
    command: str,
    execution_order: int = 50,
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Add a build hook to an initramfs profile."""
    if session is None:
        with sync_session(db_url) as sess:
            return add_initramfs_hook(
                initramfs_profile_id=initramfs_profile_id,
                hook_name=hook_name,
                hook_stage=hook_stage,
                command=command,
                execution_order=execution_order,
                enabled=enabled,
                metadata=metadata,
                session=sess,
            )

    hook = InitramfsHook(
        id=str(uuid4()),
        initramfs_profile_id=initramfs_profile_id,
        hook_name=hook_name,
        hook_stage=hook_stage,
        command=command,
        execution_order=execution_order,
        enabled=enabled,
        metadata_json=metadata,
    )
    session.add(hook)
    session.flush()

    return {
        "id": hook.id,
        "initramfs_profile_id": hook.initramfs_profile_id,
        "hook_name": hook.hook_name,
        "hook_stage": hook.hook_stage,
        "execution_order": hook.execution_order,
        "enabled": hook.enabled,
    }


def resolve_initramfs(
    profile_id: str,
    board_id: str | None = None,
    kernel_version: str | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Resolve initramfs dependencies and generate build plan."""
    if session is None:
        with sync_session(db_url) as sess:
            return resolve_initramfs(
                profile_id=profile_id,
                board_id=board_id,
                kernel_version=kernel_version,
                session=sess,
            )

    profile_data = get_initramfs_profile(profile_id, session=session)

    # Resolve packages
    resolved_packages = []
    for pkg in profile_data["packages"]:
        resolved_packages.append(
            {
                "name": pkg["package_name"],
                "version": pkg.get("version_constraint", "latest"),
                "required": pkg["required"],
            }
        )

    # Resolve scripts (sorted by execution order)
    resolved_scripts = sorted(profile_data["scripts"], key=lambda s: s["execution_order"])

    # Resolve hooks (sorted by execution order)
    resolved_hooks = sorted(
        [h for h in profile_data["hooks"] if h["enabled"]], key=lambda h: h["execution_order"]
    )

    return {
        "profile_id": profile_id,
        "board_id": board_id,
        "kernel_version": kernel_version,
        "compression": profile_data["compression"],
        "size_limit_mb": profile_data["size_limit_mb"],
        "packages": resolved_packages,
        "scripts": resolved_scripts,
        "hooks": resolved_hooks,
        "features": {
            "modules": profile_data["include_modules"],
            "firmware": profile_data["include_firmware"],
            "debug_shell": profile_data["enable_debug_shell"],
            "network": profile_data["enable_network"],
            "encryption_unlock": profile_data["enable_encryption_unlock"],
            "factory_reset": profile_data["enable_factory_reset"],
        },
    }


def validate_initramfs_profile(
    profile_id: str,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Validate initramfs profile configuration."""
    if session is None:
        with sync_session(db_url) as sess:
            return validate_initramfs_profile(profile_id, session=sess)

    profile_data = get_initramfs_profile(profile_id, session=session)

    errors = []
    warnings = []

    # Check for required packages
    if not profile_data["packages"]:
        warnings.append("No packages defined - initramfs will be minimal")

    # Check for init script
    init_scripts = [s for s in profile_data["scripts"] if s["script_type"] == "init"]
    if not init_scripts:
        errors.append("No init script defined - initramfs will not boot")

    # Check size limit
    if profile_data["size_limit_mb"] and profile_data["size_limit_mb"] < 5:
        warnings.append(f"Size limit very small: {profile_data['size_limit_mb']}MB")

    # Check encryption without required packages
    if profile_data["enable_encryption_unlock"]:
        crypto_packages = [
            p for p in profile_data["packages"] if "crypt" in p["package_name"].lower()
        ]
        if not crypto_packages:
            warnings.append("Encryption unlock enabled but no crypto packages found")

    # Check network without required packages
    if profile_data["enable_network"]:
        net_packages = [
            p
            for p in profile_data["packages"]
            if any(n in p["package_name"].lower() for n in ["net", "dhcp", "ip"])
        ]
        if not net_packages:
            warnings.append("Network enabled but no network packages found")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "profile_id": profile_id,
        "packages_count": len(profile_data["packages"]),
        "scripts_count": len(profile_data["scripts"]),
        "hooks_count": len(profile_data["hooks"]),
    }


def create_initramfs_artifact(
    initramfs_profile_id: str,
    board_id: str | None = None,
    kernel_version: str | None = None,
    artifact_id: str | None = None,
    size_bytes: int | None = None,
    compression: str | None = None,
    modules_manifest: dict[str, Any] | None = None,
    build_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Record a built initramfs artifact."""
    if session is None:
        with sync_session(db_url) as sess:
            return create_initramfs_artifact(
                initramfs_profile_id=initramfs_profile_id,
                board_id=board_id,
                kernel_version=kernel_version,
                artifact_id=artifact_id,
                size_bytes=size_bytes,
                compression=compression,
                modules_manifest=modules_manifest,
                build_hash=build_hash,
                metadata=metadata,
                session=sess,
            )

    artifact = InitramfsArtifact(
        id=str(uuid4()),
        initramfs_profile_id=initramfs_profile_id,
        board_id=board_id,
        kernel_version=kernel_version,
        artifact_id=artifact_id,
        size_bytes=size_bytes,
        compression=compression,
        modules_manifest_json=modules_manifest,
        build_hash=build_hash,
        metadata_json=metadata,
    )
    session.add(artifact)
    session.flush()

    return {
        "id": artifact.id,
        "initramfs_profile_id": artifact.initramfs_profile_id,
        "board_id": artifact.board_id,
        "kernel_version": artifact.kernel_version,
        "artifact_id": artifact.artifact_id,
        "size_bytes": artifact.size_bytes,
        "compression": artifact.compression,
        "build_hash": artifact.build_hash,
    }


# Made with Bob
