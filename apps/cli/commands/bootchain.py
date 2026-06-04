"""Boot Chain CLI commands (M31)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from osfabricum import bootchain as bootchain_service

bootchain_app = typer.Typer(help="Boot chain management commands", no_args_is_help=True)


# Seed data loader

@bootchain_app.command("seed")
def seed_boot_chains(
    catalog_dir: Annotated[
        Path, typer.Option(help="Catalog directory with seed YAML files")
    ] = Path("catalog/seed"),
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Load boot chain seed data from YAML file."""
    from osfabricum.db.seed_data import seed_boot_chains as load_boot_chains
    from osfabricum.db.session import sync_session

    boot_chains_file = catalog_dir / "boot_chains.yaml"
    
    if not boot_chains_file.exists():
        typer.echo(f"ERROR: Boot chains file not found: {boot_chains_file}", err=True)
        raise typer.Exit(code=1)

    with sync_session(db) as session:
        counts = load_boot_chains(session, boot_chains_file)
        session.commit()
        
        typer.echo(f"✓ Loaded boot chain seed data from {boot_chains_file}:")
        typer.echo(f"  - Boot chains: {counts['boot_chains']}")
        typer.echo(f"  - Templates: {counts['templates']}")
        typer.echo(f"  - Files: {counts['files']}")
        typer.echo(f"  - Bindings: {counts['bindings']}")


@bootchain_app.command("list")
def list_boot_chains(
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """List all boot chains."""
    chains = bootchain_service.list_boot_chains(db_url=db)
    if not chains:
        typer.echo("No boot chains found.")
        return
    for chain in chains:
        typer.echo(f"{chain['id']}: {chain['name']} (scheme: {chain['boot_scheme_id']})")


@bootchain_app.command("create")
def create_boot_chain(
    name: Annotated[str, typer.Argument(help="Boot chain name")],
    boot_scheme_id: Annotated[str, typer.Argument(help="Boot scheme ID")],
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    metadata: Annotated[str | None, typer.Option(help="JSON metadata")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Create a new boot chain."""
    meta: dict[str, Any] | None = None
    if metadata:
        meta = json.loads(metadata)
    
    result = bootchain_service.create_boot_chain(
        name=name,
        boot_scheme_id=boot_scheme_id,
        description=description,
        metadata=meta,
        db_url=db,
    )
    typer.echo(f"Created boot chain: {result['id']}")


@bootchain_app.command("show")
def show_boot_chain(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Show boot chain with all templates and files."""
    chain = bootchain_service.get_boot_chain(boot_chain_id, db_url=db)
    typer.echo(json.dumps(chain, indent=2))


@bootchain_app.command("add-template")
def add_template(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    template_type: Annotated[str, typer.Argument(help="Template type (e.g., grub_cfg)")],
    content_file: Annotated[str, typer.Argument(help="Path to template content file")],
    variables: Annotated[str | None, typer.Option(help="JSON variables")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add a template to a boot chain."""
    from pathlib import Path
    
    content = Path(content_file).read_text()
    vars_dict: dict[str, Any] | None = None
    if variables:
        vars_dict = json.loads(variables)
    
    result = bootchain_service.add_boot_chain_template(
        boot_chain_id=boot_chain_id,
        template_type=template_type,
        content=content,
        variables=vars_dict,
        db_url=db,
    )
    typer.echo(f"Added template: {result['id']}")


@bootchain_app.command("add-file")
def add_file(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    filename: Annotated[str, typer.Argument(help="Filename")],
    placement: Annotated[str, typer.Argument(help="Placement path (e.g., /boot)")],
    content: Annotated[str | None, typer.Option(help="Content template")] = None,
    template_id: Annotated[str | None, typer.Option(help="Template ID")] = None,
    optional: Annotated[bool, typer.Option(help="Mark as optional")] = False,
    permissions: Annotated[str | None, typer.Option(help="File permissions")] = None,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Add a file to a boot chain."""
    result = bootchain_service.add_boot_chain_file(
        boot_chain_id=boot_chain_id,
        filename=filename,
        placement=placement,
        content_template=content,
        template_id=template_id,
        required=not optional,
        permissions=permissions,
        db_url=db,
    )
    typer.echo(f"Added file: {result['id']}")


@bootchain_app.command("bind")
def bind_boot_chain(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    board_id: Annotated[str | None, typer.Option(help="Board ID")] = None,
    profile_id: Annotated[str | None, typer.Option(help="Profile ID")] = None,
    default: Annotated[bool, typer.Option(help="Set as default")] = False,
    priority: Annotated[int, typer.Option(help="Priority (higher = preferred)")] = 100,
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Bind a boot chain to a board and/or profile."""
    result = bootchain_service.bind_boot_chain(
        boot_chain_id=boot_chain_id,
        board_id=board_id,
        profile_id=profile_id,
        is_default=default,
        priority=priority,
        db_url=db,
    )
    typer.echo(f"Created binding: {result['id']}")


@bootchain_app.command("render")
def render_boot_chain(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    variables: Annotated[str, typer.Option(help="JSON variables")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Render boot chain files with provided variables."""
    vars_dict = json.loads(variables)
    result = bootchain_service.render_boot_chain(
        boot_chain_id=boot_chain_id,
        variables=vars_dict,
        db_url=db,
    )
    typer.echo(json.dumps(result, indent=2))


@bootchain_app.command("validate")
def validate_boot_chain(
    boot_chain_id: Annotated[str, typer.Argument(help="Boot chain ID")],
    context: Annotated[str, typer.Option(help="JSON context")],
    db: Annotated[
        str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")
    ] = None,
) -> None:
    """Validate that boot chain has all required components."""
    ctx = json.loads(context)
    result = bootchain_service.validate_boot_chain(
        boot_chain_id=boot_chain_id,
        context=ctx,
        db_url=db,
    )
    
    if result["valid"]:
        typer.echo("✓ Boot chain is valid")
    else:
        typer.echo("✗ Boot chain validation failed:", err=True)
        for error in result["errors"]:
            typer.echo(f"  ERROR: {error}", err=True)
    
    for warning in result["warnings"]:
        typer.echo(f"  WARNING: {warning}")
    
    typer.echo(f"Required files: {result['required_files_count']}")

# Made with Bob
