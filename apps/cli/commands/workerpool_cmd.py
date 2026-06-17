"""M67 — Distributed Build Farm / Worker Pools CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import workerpool as wp_svc
from osfabricum.db.session import sync_session

workerpool_app = typer.Typer(help="Worker pool management", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@workerpool_app.command("create")
def create_pool(
    name: Annotated[str, typer.Argument(help="Pool name")],
    pool_kind: Annotated[str, typer.Option("--kind", help="local|remote|trusted|signing-only|hardware-lab|qemu-test")] = "local",
    label: Annotated[str, typer.Option("--label")] = "",
    max_parallelism: Annotated[int, typer.Option("--parallelism")] = 4,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create a worker pool."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            p = wp_svc.create_worker_pool(
                s, name=name, pool_kind=pool_kind,
                label=label, max_parallelism=max_parallelism,
            )
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"worker-pool: {p.id}  name={p.name}  kind={p.pool_kind}  parallelism={p.max_parallelism}")


@workerpool_app.command("list")
def list_pools(
    pool_kind: Annotated[str | None, typer.Option("--kind")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List worker pools."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        pools = wp_svc.list_worker_pools(s, pool_kind=pool_kind)
    if not pools:
        typer.echo("(no worker pools)")
        return
    for p in pools:
        typer.echo(f"{p.id[:8]}  {p.name}  kind={p.pool_kind}  par={p.max_parallelism}")


@workerpool_app.command("assign")
def assign_worker(
    pool_id: Annotated[str, typer.Argument(help="Pool ID")],
    worker_id: Annotated[str | None, typer.Option("--worker")] = None,
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Add a worker to a pool."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        m = wp_svc.add_pool_member(s, pool_id=pool_id, worker_id=worker_id)
        s.commit()
        s.refresh(m)
    typer.echo(f"member: {m.id}  pool={m.worker_pool_id}  worker={m.worker_id or '—'}")


@workerpool_app.command("quota")
def set_quota(
    pool_id: Annotated[str, typer.Argument(help="Pool ID")],
    resource_kind: Annotated[str, typer.Option("--resource", help="cpu|memory|disk|network")],
    limit_value: Annotated[int, typer.Option("--limit")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Set a resource quota for a pool."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            q = wp_svc.set_pool_quota(
                s, pool_id=pool_id,
                resource_kind=resource_kind,
                limit_value=limit_value,
            )
            s.commit()
            s.refresh(q)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"quota: pool={q.pool_id}  {q.resource_kind}={q.limit_value}")
