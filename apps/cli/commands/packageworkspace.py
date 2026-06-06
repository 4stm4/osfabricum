"""Package Workspace / Package Manager CLI commands (M35).

Thin client over :mod:`osfabricum.packageworkspace`: inspect the kind/layer
taxonomy, compose and explain package cache keys, organize groups/sets, resolve
a set into a layer-ordered install plan, and pin locks. The cache key folds in
the full package identity (kernel binding for kernel-bound kinds) so a kernel
module is never reused across an incompatible kernel (G-28).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from osfabricum import packageworkspace as pw

packageworkspace_app = typer.Typer(
    help="Package Workspace (taxonomy, cache keys, groups/sets, locks)",
    no_args_is_help=True,
)

_DB = Annotated[str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")]


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR: {exc}", err=True)
    raise typer.Exit(code=1) from None


# --- taxonomy ---


@packageworkspace_app.command("kinds")
def kinds(db: _DB = None) -> None:
    """List the package kinds."""
    for k in pw.list_kinds(db_url=db):
        typer.echo(f"{k['name']:<16} {k['description'] or ''}")


@packageworkspace_app.command("layers")
def layers(db: _DB = None) -> None:
    """List the package layers (ordered)."""
    for layer in pw.list_layers(db_url=db):
        typer.echo(f"{layer['position']:>2}  {layer['name']:<14} {layer['description'] or ''}")


@packageworkspace_app.command("classify")
def classify(
    package_id: Annotated[str, typer.Argument(help="Package ID")],
    kind: Annotated[str, typer.Argument(help="Package kind")],
    layer: Annotated[str, typer.Argument(help="Package layer")],
    db: _DB = None,
) -> None:
    """Assign a kind and layer to a package."""
    try:
        result = pw.classify_package(package_id, kind=kind, layer=layer, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"{result['name']}: kind={result['kind']} layer={result['layer']}")


# --- cache ---


def _key_opts(
    name: str,
    version: str,
    arch: str,
    kind: str,
    source_hash: str,
    recipe_hash: str,
    feature_hash: str,
    libc: str,
    toolchain_hash: str,
    abi_hash: str,
    kernel_release: str | None,
    kernel_config_hash: str | None,
) -> dict[str, object]:
    return {
        "name": name,
        "version": version,
        "arch": arch,
        "kind": kind,
        "source_hash": source_hash,
        "recipe_hash": recipe_hash,
        "feature_hash": feature_hash,
        "libc": libc,
        "toolchain_hash": toolchain_hash,
        "abi_hash": abi_hash,
        "kernel_release": kernel_release,
        "kernel_config_hash": kernel_config_hash,
    }


@packageworkspace_app.command("cache-key")
def cache_key(
    name: Annotated[str, typer.Argument(help="Package name")],
    version: Annotated[str, typer.Argument(help="Package version")],
    arch: Annotated[str, typer.Argument(help="Architecture")],
    kind: Annotated[str, typer.Option(help="Package kind")] = "system",
    source_hash: Annotated[str, typer.Option(help="Source hash")] = "",
    recipe_hash: Annotated[str, typer.Option(help="Recipe hash")] = "",
    feature_hash: Annotated[str, typer.Option(help="Feature hash")] = "",
    libc: Annotated[str, typer.Option(help="libc")] = "",
    toolchain_hash: Annotated[str, typer.Option(help="Toolchain hash")] = "",
    abi_hash: Annotated[str, typer.Option(help="ABI hash")] = "",
    kernel_release: Annotated[
        str | None, typer.Option(help="Kernel release (kernel-bound)")
    ] = None,
    kernel_config_hash: Annotated[
        str | None, typer.Option(help="Kernel config hash (kernel-bound)")
    ] = None,
) -> None:
    """Compose a package cache key and print its components."""
    opts = _key_opts(
        name,
        version,
        arch,
        kind,
        source_hash,
        recipe_hash,
        feature_hash,
        libc,
        toolchain_hash,
        abi_hash,
        kernel_release,
        kernel_config_hash,
    )
    try:
        result = pw.compute_cache_key(**opts)  # type: ignore[arg-type]
    except ValueError as exc:
        _fail(exc)
    typer.echo(json.dumps(result, indent=2))


@packageworkspace_app.command("cache-lookup")
def cache_lookup(
    name: Annotated[str, typer.Argument(help="Package name")],
    version: Annotated[str, typer.Argument(help="Package version")],
    arch: Annotated[str, typer.Argument(help="Architecture")],
    kind: Annotated[str, typer.Option(help="Package kind")] = "system",
    source_hash: Annotated[str, typer.Option(help="Source hash")] = "",
    recipe_hash: Annotated[str, typer.Option(help="Recipe hash")] = "",
    feature_hash: Annotated[str, typer.Option(help="Feature hash")] = "",
    libc: Annotated[str, typer.Option(help="libc")] = "",
    toolchain_hash: Annotated[str, typer.Option(help="Toolchain hash")] = "",
    abi_hash: Annotated[str, typer.Option(help="ABI hash")] = "",
    kernel_release: Annotated[str | None, typer.Option(help="Kernel release")] = None,
    kernel_config_hash: Annotated[str | None, typer.Option(help="Kernel config hash")] = None,
    db: _DB = None,
) -> None:
    """Look a key identity up in the cache; a miss reports the differing field."""
    opts = _key_opts(
        name,
        version,
        arch,
        kind,
        source_hash,
        recipe_hash,
        feature_hash,
        libc,
        toolchain_hash,
        abi_hash,
        kernel_release,
        kernel_config_hash,
    )
    try:
        result = pw.lookup_cache(db_url=db, **opts)  # type: ignore[arg-type]
    except ValueError as exc:
        _fail(exc)
    if result["hit"]:
        typer.secho(f"HIT  {result['cache_key']}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"MISS {result['cache_key']}", fg=typer.colors.YELLOW)
        if "explain" in result:
            typer.echo(f"  differs from nearest: {', '.join(result['explain']['differs'])}")


@packageworkspace_app.command("cache-stats")
def cache_stats(db: _DB = None) -> None:
    """Show cache entry counts overall and by kind."""
    stats = pw.cache_stats(db_url=db)
    typer.echo(f"total: {stats['total']}")
    for kind, count in sorted(stats["by_kind"].items()):
        typer.echo(f"  {kind:<16} {count}")


# --- groups / sets ---


@packageworkspace_app.command("group-create")
def group_create(
    name: Annotated[str, typer.Argument(help="Group name")],
    distribution_id: Annotated[
        str | None, typer.Option(help="Distribution (omit = global)")
    ] = None,
    db: _DB = None,
) -> None:
    """Create a package group (omit --distribution-id for a reusable global group)."""
    try:
        result = pw.create_group(name, distribution_id=distribution_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created group: {result['id']}")


@packageworkspace_app.command("group-add")
def group_add(
    group_id: Annotated[str, typer.Argument(help="Group ID")],
    package_id: Annotated[str, typer.Argument(help="Package ID")],
    db: _DB = None,
) -> None:
    """Add a package to a group."""
    try:
        pw.add_to_group(group_id, package_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo("Added.")


@packageworkspace_app.command("group-list")
def group_list(db: _DB = None) -> None:
    """List package groups."""
    for g in pw.list_groups(db_url=db):
        scope = "global" if g["global"] else g["distribution_id"]
        typer.echo(f"{g['id']}  {g['name']:<20} {g['member_count']} pkgs  [{scope}]")


@packageworkspace_app.command("set-create")
def set_create(
    name: Annotated[str, typer.Argument(help="Set name")],
    distribution_id: Annotated[str | None, typer.Option(help="Distribution ID")] = None,
    db: _DB = None,
) -> None:
    """Create a package set."""
    try:
        result = pw.create_set(name, distribution_id=distribution_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Created set: {result['id']}")


@packageworkspace_app.command("set-add")
def set_add(
    set_id: Annotated[str, typer.Argument(help="Set ID")],
    member_kind: Annotated[str, typer.Argument(help="group | package")],
    member_id: Annotated[str, typer.Argument(help="Group ID or Package ID")],
    db: _DB = None,
) -> None:
    """Add a group or package to a set."""
    kwargs = {"group_id": member_id} if member_kind == "group" else {"package_id": member_id}
    try:
        pw.add_to_set(set_id, member_kind=member_kind, db_url=db, **kwargs)
    except ValueError as exc:
        _fail(exc)
    typer.echo("Added.")


@packageworkspace_app.command("set-resolve")
def set_resolve(
    set_id: Annotated[str, typer.Argument(help="Set ID")],
    db: _DB = None,
) -> None:
    """Resolve a set into a layer-ordered install plan."""
    try:
        plan = pw.resolve_set(set_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
    for p in plan["packages"]:
        typer.echo(f"  {p['position']:>2} {p['layer']:<12} {p['kind']:<14} {p['package']}")
    typer.secho(f"  {plan['plan_hash']}", fg=typer.colors.CYAN)


# --- locks ---


@packageworkspace_app.command("lock-create")
def lock_create(
    package_name: Annotated[str, typer.Argument(help="Package name")],
    version: Annotated[str, typer.Argument(help="Version")],
    reason: Annotated[str | None, typer.Option(help="Why it is pinned")] = None,
    db: _DB = None,
) -> None:
    """Pin a package to a version."""
    try:
        result = pw.create_lock(package_name, version, reason=reason, db_url=db)
    except ValueError as exc:
        _fail(exc)
    typer.echo(f"Locked: {result['id']}")


@packageworkspace_app.command("lock-list")
def lock_list(db: _DB = None) -> None:
    """List package locks."""
    for locked in pw.list_locks(db_url=db):
        typer.echo(f"{locked['package_name']}@{locked['version']}  {locked['reason'] or ''}")
