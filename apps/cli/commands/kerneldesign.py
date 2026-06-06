"""Kernel / Driver Designer CLI commands (M33).

Thin client over :mod:`osfabricum.kerneldesign`: list/search a Kconfig index,
resolve a requested option set through the typed dependency graph, render the
``.config``, and manage driver bundles. Mutations live behind the API's write
auth; the CLI talks to the service layer directly (operator-local).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from osfabricum import kerneldesign as kd

kerneldesign_app = typer.Typer(
    help="Kernel / Driver Designer (Kconfig graph, driver bundles)",
    no_args_is_help=True,
)

_DB = Annotated[str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")]


def _parse_sets(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``--set SYMBOL=value`` options into a map."""
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            typer.echo(f"ERROR: --set expects SYMBOL=value, got {pair!r}", err=True)
            raise typer.Exit(code=1)
        key, _, value = pair.partition("=")
        out[key.strip()] = value.strip()
    return out


@kerneldesign_app.command("index-list")
def index_list(db: _DB = None) -> None:
    """List ingested Kconfig indexes."""
    rows = kd.list_indexes(db_url=db)
    if not rows:
        typer.echo("No Kconfig indexes found.")
        return
    for r in rows:
        typer.echo(
            f"{r['id']}  {r['arch']:<8} {r['symbol_count']:>5} symbols"
            f"  kernel={r['kernel_id']}  ref={r['source_ref'] or '—'}"
        )


@kerneldesign_app.command("search")
def search(
    index_id: Annotated[str, typer.Argument(help="Kconfig index ID")],
    query: Annotated[str, typer.Argument(help="Substring of symbol name or prompt")],
    db: _DB = None,
) -> None:
    """Search Kconfig symbols within an index."""
    try:
        rows = kd.search_options(index_id, query, db_url=db)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    if not rows:
        typer.echo("No matching symbols.")
        return
    for r in rows:
        flag = "" if r["user_selectable"] else "  (hidden)"
        typer.echo(f"{r['name']:<32} {r['type']:<8} {r['prompt'] or ''}{flag}")


@kerneldesign_app.command("show")
def show(
    index_id: Annotated[str, typer.Argument(help="Kconfig index ID")],
    symbol: Annotated[str, typer.Argument(help="Symbol name")],
    db: _DB = None,
) -> None:
    """Show a symbol with its dependency edges."""
    try:
        result = kd.get_option(index_id, symbol, db_url=db)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(result, indent=2))


@kerneldesign_app.command("resolve")
def resolve(
    index_id: Annotated[str, typer.Argument(help="Kconfig index ID")],
    set_: Annotated[list[str], typer.Option("--set", help="SYMBOL=value (repeatable)")] = [],  # noqa: B006 — typer fills a fresh list per invocation
    output: Annotated[str, typer.Option("--output", "-o", help="table | json")] = "table",
    db: _DB = None,
) -> None:
    """Resolve a requested option set through the Kconfig graph."""
    try:
        result = kd.resolve_config(index_id, _parse_sets(set_), db_url=db)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None

    if output == "json":
        typer.echo(json.dumps(result, indent=2))
    else:
        for name in sorted(result["resolved"]):
            src = result["explain"].get(name, "")
            typer.echo(f"  CONFIG_{name}={result['resolved'][name]:<4} ({src})")
        for w in result["warnings"]:
            typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)
        for e in result["errors"]:
            typer.secho(f"  error: {e}", fg=typer.colors.RED, err=True)
        typer.echo("✓ valid" if result["valid"] else "✗ invalid")

    if not result["valid"]:
        raise typer.Exit(code=1)


@kerneldesign_app.command("render")
def render(
    index_id: Annotated[str, typer.Argument(help="Kconfig index ID")],
    set_: Annotated[list[str], typer.Option("--set", help="SYMBOL=value (repeatable)")] = [],  # noqa: B006 — typer fills a fresh list per invocation
    db: _DB = None,
) -> None:
    """Resolve then render the requested options to ``.config`` text."""
    try:
        resolved = kd.resolve_config(index_id, _parse_sets(set_), db_url=db)
        if not resolved["valid"]:
            for e in resolved["errors"]:
                typer.secho(f"  error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        rendered = kd.render_config(index_id, resolved["resolved"], db_url=db)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(rendered["content"], nl=False)
    typer.secho(f"# {rendered['config_hash']}", fg=typer.colors.CYAN)


@kerneldesign_app.command("bundle-list")
def bundle_list(db: _DB = None) -> None:
    """List driver bundles."""
    rows = kd.list_driver_bundles(db_url=db)
    if not rows:
        typer.echo("No driver bundles found.")
        return
    for r in rows:
        typer.echo(f"{r['id']}  {r['name']}  {r['description'] or ''}")


@kerneldesign_app.command("bundle-create")
def bundle_create(
    name: Annotated[str, typer.Argument(help="Bundle name")],
    kernel_id: Annotated[str | None, typer.Option(help="Kernel ID")] = None,
    description: Annotated[str | None, typer.Option(help="Description")] = None,
    db: _DB = None,
) -> None:
    """Create a driver bundle."""
    try:
        result = kd.create_driver_bundle(
            name, kernel_id=kernel_id, description=description, db_url=db
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Created driver bundle: {result['id']}")


@kerneldesign_app.command("bundle-resolve")
def bundle_resolve(
    bundle_id: Annotated[str, typer.Argument(help="Driver bundle ID")],
    db: _DB = None,
) -> None:
    """Expand a bundle into options, modules, firmware and DT overlays."""
    try:
        result = kd.resolve_driver_bundle(bundle_id, db_url=db)
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(result, indent=2))
