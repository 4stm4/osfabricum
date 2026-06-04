"""Board/BSP CLI commands (M30)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from osfabricum import board as board_service

board_app = typer.Typer(help="Board/BSP management commands", no_args_is_help=True)


# Seed data loader

@board_app.command("seed")
def seed_bsp_data(
    catalog_dir: Annotated[
        Path, typer.Option(help="Catalog directory with seed YAML files")
    ] = Path("catalog/seed"),
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Load BSP seed data from YAML files."""
    from osfabricum.db.seed_data import (
        seed_board_bsp_from_yaml,
        seed_board_revisions_from_yaml,
        seed_soc_families_from_yaml,
    )
    from osfabricum.db.session import sync_session

    if not catalog_dir.exists():
        typer.echo(f"ERROR: Catalog directory not found: {catalog_dir}", err=True)
        raise typer.Exit(code=1)

    with sync_session(db) as session:
        # Load SoC families
        soc_file = catalog_dir / "soc_families.yaml"
        if soc_file.exists():
            count = seed_soc_families_from_yaml(session, soc_file)
            typer.echo(f"Loaded {count} SoC families from {soc_file}")
        
        # Load board revisions
        rev_file = catalog_dir / "board_revisions.yaml"
        if rev_file.exists():
            count = seed_board_revisions_from_yaml(session, rev_file)
            typer.echo(f"Loaded {count} board revisions from {rev_file}")
        
        # Load BSP data
        bsp_file = catalog_dir / "board_bsp.yaml"
        if bsp_file.exists():
            counts = seed_board_bsp_from_yaml(session, bsp_file)
            typer.echo(f"Loaded BSP data from {bsp_file}:")
            for key, count in counts.items():
                typer.echo(f"  {key}: {count}")
        
        session.commit()
        typer.echo("BSP seed data loaded successfully!")


# SoC Families

@board_app.command("soc-list")
def soc_list(
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """List all SoC families."""
    families = board_service.list_soc_families(db_url=db)
    if not families:
        typer.echo("No SoC families found.")
        return
    for fam in families:
        typer.echo(f"{fam['id']}: {fam['name']} ({fam.get('vendor', 'N/A')})")


@board_app.command("soc-create")
def soc_create(
    name: Annotated[str, typer.Argument(help="SoC family name")],
    vendor: Annotated[str | None, typer.Option(help="SoC vendor")] = None,
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Create a new SoC family."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    result = board_service.create_soc_family(
        name=name,
        vendor=vendor,
        description=description,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Created SoC family: {result['id']}")


# Board Revisions

@board_app.command("revision-list")
def revision_list(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """List all revisions for a board."""
    revisions = board_service.list_board_revisions(board_id, db_url=db)
    if not revisions:
        typer.echo(f"No revisions found for board {board_id}.")
        return
    for rev in revisions:
        default = " (default)" if rev.get("is_default") else ""
        typer.echo(f"{rev['id']}: {rev['revision']}{default}")


@board_app.command("revision-create")
def revision_create(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    revision: Annotated[str, typer.Argument(help="Revision name")],
    soc_family: Annotated[str | None, typer.Option(help="SoC family ID")] = None,
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    default: Annotated[bool, typer.Option(help="Set as default revision")] = False,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Create a new board revision."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    result = board_service.create_board_revision(
        board_id=board_id,
        revision=revision,
        soc_family_id=soc_family,
        description=description,
        is_default=default,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Created board revision: {result['id']}")


# Board BSP (full view)

@board_app.command("bsp-show")
def bsp_show(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Show board with all BSP data."""
    data = board_service.get_board_with_bsp(board_id, db_url=db)
    typer.echo(json.dumps(data, indent=2))


# Board Firmware

@board_app.command("firmware-add")
def firmware_add(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    filename: Annotated[str, typer.Argument(help="Firmware filename")],
    source_uri: Annotated[str | None, typer.Option(help="Source URI")] = None,
    source_ref: Annotated[str | None, typer.Option(help="Source ref (branch/tag)")] = None,
    expected_hash: Annotated[str | None, typer.Option("--hash", help="Expected hash")] = None,
    optional: Annotated[bool, typer.Option(help="Mark as optional")] = False,
    placement: Annotated[str | None, typer.Option(help="Placement location")] = None,
    revision: Annotated[str | None, typer.Option(help="Board revision ID")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add firmware blob to a board."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    result = board_service.add_board_firmware(
        board_id=board_id,
        filename=filename,
        source_uri=source_uri,
        source_ref=source_ref,
        expected_hash=expected_hash,
        required=not optional,
        placement=placement,
        board_revision_id=revision,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Added firmware: {result['id']}")


# Board Device Trees

@board_app.command("dtb-add")
def dtb_add(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    filename: Annotated[str, typer.Argument(help="Device tree filename")],
    dtb_type: Annotated[str, typer.Argument(help="Type: base or overlay")],
    source_uri: Annotated[str | None, typer.Option(help="Source URI")] = None,
    source_ref: Annotated[str | None, typer.Option(help="Source ref (branch/tag)")] = None,
    expected_hash: Annotated[str | None, typer.Option("--hash", help="Expected hash")] = None,
    optional: Annotated[bool, typer.Option(help="Mark as optional")] = False,
    placement: Annotated[str | None, typer.Option(help="Placement location")] = None,
    revision: Annotated[str | None, typer.Option(help="Board revision ID")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add device tree to a board."""
    if dtb_type not in ("base", "overlay"):
        typer.echo("ERROR: dtb_type must be 'base' or 'overlay'", err=True)
        raise typer.Exit(code=1)
    
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    result = board_service.add_board_device_tree(
        board_id=board_id,
        filename=filename,
        dtb_type=dtb_type,
        source_uri=source_uri,
        source_ref=source_ref,
        expected_hash=expected_hash,
        required=not optional,
        placement=placement,
        board_revision_id=revision,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Added device tree: {result['id']}")


# Board Flash Methods

@board_app.command("flash-add")
def flash_add(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    method_name: Annotated[str, typer.Argument(help="Flash method name")],
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    command_template: Annotated[str | None, typer.Option("--command", help="Command template")] = None,
    tools: Annotated[str | None, typer.Option(help="Required tools (comma-separated)")] = None,
    device_pattern: Annotated[str | None, typer.Option(help="Device pattern")] = None,
    default: Annotated[bool, typer.Option(help="Set as default method")] = False,
    revision: Annotated[str | None, typer.Option(help="Board revision ID")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add flash method to a board."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    requires_tools: list[str] | None = None
    if tools:
        requires_tools = [t.strip() for t in tools.split(",")]
    
    result = board_service.add_board_flash_method(
        board_id=board_id,
        method_name=method_name,
        description=description,
        command_template=command_template,
        requires_tools=requires_tools,
        device_pattern=device_pattern,
        is_default=default,
        board_revision_id=revision,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Added flash method: {result['id']}")


# Board Test Methods

@board_app.command("test-add")
def test_add(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    method_name: Annotated[str, typer.Argument(help="Test method name")],
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    test_command: Annotated[str | None, typer.Option("--command", help="Test command")] = None,
    tools: Annotated[str | None, typer.Option(help="Required tools (comma-separated)")] = None,
    timeout_seconds: Annotated[int | None, typer.Option("--timeout", help="Timeout in seconds")] = None,
    default: Annotated[bool, typer.Option(help="Set as default method")] = False,
    revision: Annotated[str | None, typer.Option(help="Board revision ID")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add test method to a board."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    requires_tools: list[str] | None = None
    if tools:
        requires_tools = [t.strip() for t in tools.split(",")]
    
    result = board_service.add_board_test_method(
        board_id=board_id,
        method_name=method_name,
        description=description,
        test_command=test_command,
        requires_tools=requires_tools,
        timeout_seconds=timeout_seconds,
        is_default=default,
        board_revision_id=revision,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Added test method: {result['id']}")


# Board Probe Profiles

@board_app.command("probe-add")
def probe_add(
    board_id: Annotated[str, typer.Argument(help="Board ID")],
    probe_method: Annotated[str, typer.Argument(help="Probe method")],
    match_pattern: Annotated[str | None, typer.Option("--pattern", help="Match pattern")] = None,
    match_fields: Annotated[str | None, typer.Option("--fields", help="Match fields (JSON)")] = None,
    confidence: Annotated[int, typer.Option(help="Confidence (0-100)")] = 100,
    revision: Annotated[str | None, typer.Option(help="Board revision ID")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add probe profile to a board."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    fields: dict[str, Any] | None = None
    if match_fields:
        fields = json.loads(match_fields)
    
    result = board_service.add_board_probe_profile(
        board_id=board_id,
        probe_method=probe_method,
        match_pattern=match_pattern,
        match_fields=fields,
        confidence=confidence,
        board_revision_id=revision,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Added probe profile: {result['id']}")

# Made with Bob
