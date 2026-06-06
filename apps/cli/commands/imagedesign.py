"""Filesystem / Image Recipe Designer CLI commands (M34).

Thin client over :mod:`osfabricum.imagedesign`: define filesystem profiles, size
policies and partition layouts, assemble an image recipe, and compute a
deterministic size estimate — so image sizes/formats come from data, not the
old hardcoded pipeline constants (G-06).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from osfabricum import imagedesign as imd

imagedesign_app = typer.Typer(
    help="Filesystem / Image Recipe Designer (recipes, layouts, sizing)",
    no_args_is_help=True,
)

_DB = Annotated[str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")]


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR: {exc}", err=True)
    raise typer.Exit(code=1) from None


# --- filesystem profiles ---


@imagedesign_app.command("fs-create")
def fs_create(
    name: Annotated[str, typer.Argument(help="Profile name")],
    fs_type: Annotated[
        str, typer.Argument(help="ext4|squashfs|erofs|btrfs|xfs|vfat|overlayfs|tmpfs")
    ],
    label: Annotated[str | None, typer.Option(help="Filesystem label")] = None,
    mount_point: Annotated[str | None, typer.Option(help="Mount point")] = None,
    read_only: Annotated[bool, typer.Option(help="Read-only filesystem")] = False,
    compression: Annotated[str | None, typer.Option(help="zstd|lz4|gzip")] = None,
    db: _DB = None,
) -> None:
    """Create a reusable filesystem profile."""
    try:
        result = imd.create_filesystem_profile(
            name,
            fs_type,
            label=label,
            mount_point=mount_point,
            read_only=read_only,
            compression=compression,
            db_url=db,
        )
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created filesystem profile: {result['id']}")


@imagedesign_app.command("fs-list")
def fs_list(db: _DB = None) -> None:
    """List filesystem profiles."""
    rows = imd.list_filesystem_profiles(db_url=db)
    if not rows:
        typer.echo("No filesystem profiles found.")
        return
    for r in rows:
        ro = " ro" if r["read_only"] else ""
        typer.echo(f"{r['id']}  {r['name']:<20} {r['fs_type']}{ro}")


# --- size policies ---


@imagedesign_app.command("size-create")
def size_create(
    name: Annotated[str, typer.Argument(help="Policy name")],
    free_space_pct: Annotated[int, typer.Option(help="Extra free %% on grow partition")] = 0,
    min_free_mb: Annotated[int, typer.Option(help="Minimum free MiB")] = 0,
    align_mb: Annotated[int, typer.Option(help="Partition alignment (MiB)")] = 4,
    reserve_mb: Annotated[int, typer.Option(help="Leading/trailing reserve (MiB)")] = 1,
    db: _DB = None,
) -> None:
    """Create a reusable size policy."""
    try:
        result = imd.create_size_policy(
            name,
            free_space_pct=free_space_pct,
            min_free_mb=min_free_mb,
            align_mb=align_mb,
            reserve_mb=reserve_mb,
            db_url=db,
        )
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created size policy: {result['id']}")


@imagedesign_app.command("size-list")
def size_list(db: _DB = None) -> None:
    """List size policies."""
    rows = imd.list_size_policies(db_url=db)
    if not rows:
        typer.echo("No size policies found.")
        return
    for r in rows:
        typer.echo(
            f"{r['id']}  {r['name']:<16} align={r['align_mb']} reserve={r['reserve_mb']} "
            f"free={r['free_space_pct']}%% min_free={r['min_free_mb']}"
        )


# --- partition layouts ---


@imagedesign_app.command("layout-create")
def layout_create(
    name: Annotated[str, typer.Argument(help="Layout name")],
    board_id: Annotated[str | None, typer.Option(help="Board ID")] = None,
    db: _DB = None,
) -> None:
    """Create a partition layout."""
    try:
        result = imd.create_partition_layout(name, board_id=board_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created partition layout: {result['id']}")


@imagedesign_app.command("layout-add")
def layout_add(
    layout_id: Annotated[str, typer.Argument(help="Layout ID")],
    name: Annotated[str, typer.Argument(help="Partition name")],
    role: Annotated[str, typer.Argument(help="boot|esp|rootfs|recovery|data|ab_a|ab_b|swap")],
    filesystem_id: Annotated[str | None, typer.Option(help="Filesystem profile ID")] = None,
    size_mb: Annotated[int | None, typer.Option(help="Size in MiB (omit for grow)")] = None,
    grow: Annotated[bool, typer.Option(help="Grow to fill free space")] = False,
    db: _DB = None,
) -> None:
    """Add a partition to a layout."""
    try:
        result = imd.add_partition(
            layout_id,
            name,
            role,
            filesystem_id=filesystem_id,
            size_mb=size_mb,
            grow=grow,
            db_url=db,
        )
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Added partition: {result['id']}")


@imagedesign_app.command("layout-list")
def layout_list(db: _DB = None) -> None:
    """List partition layouts."""
    rows = imd.list_partition_layouts(db_url=db)
    if not rows:
        typer.echo("No partition layouts found.")
        return
    for r in rows:
        typer.echo(f"{r['id']}  {r['name']:<20} {r['partition_count']} partitions")


# --- image recipes ---


@imagedesign_app.command("recipe-create")
def recipe_create(
    name: Annotated[str, typer.Argument(help="Recipe name")],
    output_format: Annotated[str, typer.Option(help="Primary output format")] = "raw",
    layout: Annotated[str | None, typer.Option(help="Partition layout ID")] = None,
    size_policy: Annotated[str | None, typer.Option(help="Size policy ID")] = None,
    root_fs: Annotated[str | None, typer.Option(help="Root filesystem profile ID")] = None,
    db: _DB = None,
) -> None:
    """Create an image recipe."""
    try:
        result = imd.create_recipe(
            name,
            output_format=output_format,
            partition_layout_id=layout,
            size_policy_id=size_policy,
            root_filesystem_id=root_fs,
            db_url=db,
        )
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created image recipe: {result['id']}")


@imagedesign_app.command("recipe-list")
def recipe_list(db: _DB = None) -> None:
    """List image recipes."""
    rows = imd.list_recipes(db_url=db)
    if not rows:
        typer.echo("No image recipes found.")
        return
    for r in rows:
        layout = "" if r["has_layout"] else "  (no layout)"
        typer.echo(f"{r['id']}  {r['name']:<20} [{', '.join(r['formats'])}]{layout}")


@imagedesign_app.command("recipe-show")
def recipe_show(
    recipe_id: Annotated[str, typer.Argument(help="Recipe ID")],
    db: _DB = None,
) -> None:
    """Show a recipe's full expanded definition."""
    try:
        result = imd.resolve_recipe(recipe_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(json.dumps(result, indent=2))


@imagedesign_app.command("add-output")
def add_output(
    recipe_id: Annotated[str, typer.Argument(help="Recipe ID")],
    output_format: Annotated[str, typer.Argument(help="Output format")],
    compression: Annotated[str | None, typer.Option(help="gzip|zstd|xz")] = None,
    db: _DB = None,
) -> None:
    """Add an additional output format to a recipe."""
    try:
        result = imd.add_output(recipe_id, output_format, compression=compression, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Added output: {result['id']}")


@imagedesign_app.command("estimate")
def estimate(
    recipe_id: Annotated[str, typer.Argument(help="Recipe ID")],
    total_disk_mb: Annotated[int | None, typer.Option(help="Total disk size (MiB)")] = None,
    output: Annotated[str, typer.Option("--output", "-o", help="table | json")] = "table",
    db: _DB = None,
) -> None:
    """Compute a deterministic partition-size plan for a recipe."""
    try:
        result = imd.estimate_recipe(recipe_id, total_disk_mb=total_disk_mb, db_url=db)
    except ValueError as exc:
        _fail(exc)

    if output == "json":
        typer.echo(json.dumps(result, indent=2))
    else:
        for p in result["partitions"]:
            grow = " (grow)" if p["grow"] else ""
            typer.echo(
                f"  {p['name']:<12} {p['role']:<10} {p['size_mb']:>8} MiB"
                f"  {p['fs_type'] or '—'}{grow}"
            )
        typer.echo(f"  {'TOTAL':<12} {'':<10} {result['total_image_mb']:>8} MiB")
        typer.echo(f"  outputs: {', '.join(result['outputs'])}")
        for w in result["warnings"]:
            typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)
        for e in result["errors"]:
            typer.secho(f"  error: {e}", fg=typer.colors.RED, err=True)
        typer.secho(f"  {result['plan_hash']}", fg=typer.colors.CYAN)
        typer.echo("✓ valid" if result["valid"] else "✗ invalid")

    if not result["valid"]:
        raise typer.Exit(code=1)
