"""Package Feed / Repository Publisher CLI commands (M37).

Thin client over :mod:`osfabricum.packageworkspace` feed functions:
create, show, scope and publish signed package feeds.
"""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import packageworkspace as pw

feed_app = typer.Typer(
    help="Package Feed / Repository Publisher (M37)",
    no_args_is_help=True,
)

_DB = Annotated[str | None, typer.Option("--db", envvar="OSF_DATABASE_URL", help="Database URL")]


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR: {exc}", err=True)
    raise typer.Exit(code=1) from None


@feed_app.command("list")
def feed_list(db: _DB = None) -> None:
    """List all package feeds."""
    feeds = pw.list_feeds(db_url=db)
    if not feeds:
        typer.echo("No feeds.")
        return
    for f in feeds:
        typer.echo(f"{f['id'][:8]}  {f['name']:<24} [{f['channel']}]  {f['description'] or ''}")


@feed_app.command("create")
def feed_create(
    name: str = typer.Argument(..., help="Feed name (unique)"),
    channel: str = typer.Option("stable", "--channel", "-c", help="Channel (stable/edge/lts/…)"),
    description: str | None = typer.Option(None, "--description", "-d"),
    db: _DB = None,
) -> None:
    """Create a new package feed."""
    try:
        f = pw.create_feed(name, channel=channel, description=description, db_url=db)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"Created feed {f['id']}  {f['name']}  [{f['channel']}]")


@feed_app.command("show")
def feed_show(
    feed_id: str = typer.Argument(..., help="Feed ID or prefix"),
    db: _DB = None,
) -> None:
    """Show a feed: index entries, scoping channels and last signature."""
    try:
        f = pw.get_feed(feed_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"Feed:    {f['name']}  [{f['channel']}]  id={f['id']}")
    typer.echo(f"Desc:    {f['description'] or '(none)'}")
    sig = f["last_signature"]
    if sig:
        typer.echo(
            f"Signed:  {sig['index_hash'][:40]}  ({sig['entry_count']} entries)"
            f"  @ {sig['signed_at']}"
        )
    else:
        typer.echo("Signed:  (not yet published)")
    typer.echo(f"\nIndex ({len(f['entries'])} entries):")
    for e in f["entries"]:
        ck = (e["cache_key"] or "")[:20]
        typer.echo(f"  {e['position']:3d}  {e['package_name']:<24} {e['version']:<16} {ck}")
    channels = f["channels"]
    if channels:
        typer.echo(f"\nScope ({len(channels)} rules):")
        for c in channels:
            parts = [
                p
                for k, p in [
                    ("distribution", c["distribution"]),
                    ("arch", c["arch"]),
                    ("libc", c["libc"]),
                    ("kernel_release", c["kernel_release"]),
                ]
                if p
            ]
            typer.echo(f"  {c['id'][:8]}  {', '.join(parts) or '(any)'}")


@feed_app.command("index-add")
def feed_index_add(
    feed_id: str = typer.Argument(..., help="Feed ID"),
    package_name: str = typer.Argument(...),
    version: str = typer.Argument(...),
    cache_key: str | None = typer.Option(None, "--cache-key"),
    db: _DB = None,
) -> None:
    """Add a package@version entry to the feed index."""
    try:
        e = pw.add_feed_index(feed_id, package_name, version, cache_key=cache_key, db_url=db)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"Added  {e['package_name']}  feed={e['feed_id'][:8]}")


@feed_app.command("scope")
def feed_scope(
    feed_id: str = typer.Argument(..., help="Feed ID"),
    distribution: str | None = typer.Option(None, "--distribution", "-D"),
    arch: str | None = typer.Option(None, "--arch", "-a"),
    libc: str | None = typer.Option(None, "--libc", "-l"),
    kernel_release: str | None = typer.Option(None, "--kernel-release", "-k"),
    db: _DB = None,
) -> None:
    """Add a scope rule to the feed (distribution/arch/libc/kernel)."""
    try:
        c = pw.scope_feed(
            feed_id,
            distribution=distribution,
            arch=arch,
            libc=libc,
            kernel_release=kernel_release,
            db_url=db,
        )
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"Scoped feed {feed_id[:8]}  channel-id={c['id'][:8]}")


@feed_app.command("promote")
def feed_promote(
    package_name: str = typer.Argument(...),
    version: str = typer.Argument(...),
    to_channel: str = typer.Option(..., "--to", help="Target channel"),
    from_channel: str | None = typer.Option(None, "--from", help="Source channel"),
    db: _DB = None,
) -> None:
    """Promote a package@version from one channel to another."""
    p = pw.promote(package_name, version, to_channel, from_channel=from_channel, db_url=db)
    typer.echo(f"Promoted {p['package_name']} {p['version']} → {p['to_channel']}")


@feed_app.command("publish")
def feed_publish(
    feed_id: str = typer.Argument(..., help="Feed ID"),
    db: _DB = None,
) -> None:
    """Build the feed index, sign it and record the publish job."""
    try:
        result = pw.publish_feed(feed_id, db_url=db)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(
        f"Published feed {result['feed_id'][:8]}"
        f"  entries={result['entry_count']}"
        f"  hash={result['index_hash'][:40]}"
    )
