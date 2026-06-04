"""Initramfs CLI commands (M32)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from osfabricum import initramfs as initramfs_service

initramfs_app = typer.Typer(help="Initramfs management commands", no_args_is_help=True)


# Seed data loader


@initramfs_app.command("seed")
def seed_initramfs(
    catalog_dir: Annotated[
        Path, typer.Option(help="Catalog directory with seed YAML files")
    ] = Path("catalog/seed"),
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Load initramfs profiles seed data from YAML file."""
    from osfabricum.db.seed_data import seed_initramfs_profiles
    from osfabricum.db.session import sync_session

    initramfs_file = catalog_dir / "initramfs_profiles.yaml"

    if not initramfs_file.exists():
        typer.echo(f"ERROR: Initramfs profiles file not found: {initramfs_file}", err=True)
        raise typer.Exit(code=1)

    with sync_session(db) as session:
        counts = seed_initramfs_profiles(session, initramfs_file)
        session.commit()

        typer.echo(f"✓ Loaded initramfs seed data from {initramfs_file}:")
        typer.echo(f"  - Profiles: {counts['profiles']}")
        typer.echo(f"  - Packages: {counts['packages']}")
        typer.echo(f"  - Scripts: {counts['scripts']}")
        typer.echo(f"  - Hooks: {counts['hooks']}")


@initramfs_app.command("list")
def list_profiles(
    profile_type: Annotated[str | None, typer.Option(help="Filter by profile type")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """List all initramfs profiles."""
    profiles = initramfs_service.list_initramfs_profiles(profile_type=profile_type, db_url=db)
    if not profiles:
        typer.echo("No initramfs profiles found.")
        return
    for profile in profiles:
        features = []
        if profile.get("enable_debug_shell"):
            features.append("debug")
        if profile.get("enable_network"):
            features.append("network")
        if profile.get("enable_encryption_unlock"):
            features.append("encryption")
        features_str = f" [{', '.join(features)}]" if features else ""
        typer.echo(f"{profile['id']}: {profile['name']} ({profile['profile_type']}){features_str}")


@initramfs_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    profile_type: Annotated[
        str, typer.Argument(help="Profile type (minimal, recovery, encrypted, network, debug)")
    ],
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    compression: Annotated[str, typer.Option(help="Compression (zstd, gzip, xz)")] = "zstd",
    size_limit_mb: Annotated[int | None, typer.Option(help="Size limit in MB")] = None,
    modules: Annotated[bool, typer.Option(help="Include kernel modules")] = True,
    firmware: Annotated[bool, typer.Option(help="Include firmware")] = False,
    debug_shell: Annotated[bool, typer.Option(help="Enable debug shell")] = False,
    network: Annotated[bool, typer.Option(help="Enable network")] = False,
    encryption: Annotated[bool, typer.Option(help="Enable encryption unlock")] = False,
    factory_reset: Annotated[bool, typer.Option(help="Enable factory reset")] = False,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Create a new initramfs profile."""
    result = initramfs_service.create_initramfs_profile(
        name=name,
        profile_type=profile_type,
        description=description,
        compression=compression,
        size_limit_mb=size_limit_mb,
        include_modules=modules,
        include_firmware=firmware,
        enable_debug_shell=debug_shell,
        enable_network=network,
        enable_encryption_unlock=encryption,
        enable_factory_reset=factory_reset,
        db_url=db,
    )
    typer.echo(f"Created initramfs profile: {result['id']}")


@initramfs_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Show initramfs profile details."""
    profile = initramfs_service.get_initramfs_profile(profile_id, db_url=db)
    typer.echo(json.dumps(profile, indent=2))


@initramfs_app.command("add-package")
def add_package(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    package_name: Annotated[str, typer.Argument(help="Package name")],
    version: Annotated[str | None, typer.Option(help="Version constraint")] = None,
    required: Annotated[bool, typer.Option(help="Is required")] = True,
    priority: Annotated[int, typer.Option(help="Priority")] = 100,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add a package to an initramfs profile."""
    result = initramfs_service.add_initramfs_package(
        initramfs_profile_id=profile_id,
        package_name=package_name,
        version_constraint=version,
        required=required,
        priority=priority,
        db_url=db,
    )
    typer.echo(f"Added package: {result['id']}")


@initramfs_app.command("add-script")
def add_script(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    script_name: Annotated[str, typer.Argument(help="Script name")],
    script_type: Annotated[str, typer.Argument(help="Script type (init, mount, network, unlock)")],
    content_file: Annotated[str, typer.Argument(help="Path to script content file")],
    order: Annotated[int, typer.Option(help="Execution order")] = 50,
    required: Annotated[bool, typer.Option(help="Is required")] = True,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add a script to an initramfs profile."""
    content = Path(content_file).read_text()
    result = initramfs_service.add_initramfs_script(
        initramfs_profile_id=profile_id,
        script_name=script_name,
        script_type=script_type,
        content=content,
        execution_order=order,
        required=required,
        db_url=db,
    )
    typer.echo(f"Added script: {result['id']}")


@initramfs_app.command("add-hook")
def add_hook(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    hook_name: Annotated[str, typer.Argument(help="Hook name")],
    hook_stage: Annotated[
        str, typer.Argument(help="Hook stage (pre-build, post-build, pre-pack, post-pack)")
    ],
    command: Annotated[str, typer.Argument(help="Command to execute")],
    order: Annotated[int, typer.Option(help="Execution order")] = 50,
    enabled: Annotated[bool, typer.Option(help="Is enabled")] = True,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add a build hook to an initramfs profile."""
    result = initramfs_service.add_initramfs_hook(
        initramfs_profile_id=profile_id,
        hook_name=hook_name,
        hook_stage=hook_stage,
        command=command,
        execution_order=order,
        enabled=enabled,
        db_url=db,
    )
    typer.echo(f"Added hook: {result['id']}")


@initramfs_app.command("resolve")
def resolve_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    board: Annotated[str | None, typer.Option(help="Board ID")] = None,
    kernel: Annotated[str | None, typer.Option(help="Kernel version")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Resolve initramfs dependencies and generate build plan."""
    result = initramfs_service.resolve_initramfs(
        profile_id=profile_id,
        board_id=board,
        kernel_version=kernel,
        db_url=db,
    )
    typer.echo(json.dumps(result, indent=2))


@initramfs_app.command("validate")
def validate_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Validate initramfs profile configuration."""
    result = initramfs_service.validate_initramfs_profile(profile_id, db_url=db)

    if result["valid"]:
        typer.echo("✓ Initramfs profile is valid")
    else:
        typer.echo("✗ Initramfs profile validation failed:", err=True)
        for error in result["errors"]:
            typer.echo(f"  ERROR: {error}", err=True)

    for warning in result["warnings"]:
        typer.echo(f"  WARNING: {warning}")

    typer.echo(
        f"Packages: {result['packages_count']}, "
        f"Scripts: {result['scripts_count']}, Hooks: {result['hooks_count']}"
    )


# Made with Bob
