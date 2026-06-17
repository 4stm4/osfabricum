"""M68 — Build Isolation / Sandbox Policy CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from osfabricum import isolation as iso_svc
from osfabricum.db.session import sync_session

isolation_app = typer.Typer(help="Isolation and sandbox policies", no_args_is_help=True)

_DB = typer.Option(None, "--db-url", envvar="OSFABRICUM_DB_URL")


@isolation_app.command("create")
def create_policy(
    name: Annotated[str, typer.Argument(help="Policy name")],
    mode: Annotated[str, typer.Option("--mode", help="none|chroot|bubblewrap|nspawn|podman|firecracker|vm")] = "none",
    label: Annotated[str, typer.Option("--label")] = "",
    network: Annotated[bool, typer.Option("--network/--no-network")] = True,
    write_access: Annotated[str, typer.Option("--write-access", help="none|build-dir|full")] = "build-dir",
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Create an isolation policy."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            p = iso_svc.create_isolation_policy(
                s, name=name, mode=mode, label=label,
                network_allowed=network, write_access=write_access,
            )
            s.commit()
            s.refresh(p)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
    typer.echo(f"isolation-policy: {p.id}  name={p.name}  mode={p.mode}  net={'Y' if p.network_allowed else 'N'}")


@isolation_app.command("list")
def list_policies(
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """List isolation policies."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        policies = iso_svc.list_isolation_policies(s)
    if not policies:
        typer.echo("(no isolation policies)")
        return
    for p in policies:
        typer.echo(f"{p.id[:8]}  {p.name}  mode={p.mode}  write={p.write_access}  net={'Y' if p.network_allowed else 'N'}")


@isolation_app.command("check")
def check_policy(
    policy_id: Annotated[str, typer.Argument(help="Policy ID")],
    required_mode: Annotated[str, typer.Argument(help="Required isolation mode")],
    db_url: Annotated[str | None, _DB] = None,
) -> None:
    """Check if a policy satisfies a required isolation mode."""
    from osfabricum.settings import load_settings
    url = db_url or load_settings().database.url
    with sync_session(url) as s:
        try:
            policy = iso_svc.get_isolation_policy(s, policy_id)
        except KeyError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(1) from None
        ok = iso_svc.policy_satisfies(policy, required_mode)
    status = "PASS" if ok else "FAIL"
    typer.echo(f"[{status}] policy={policy.mode}  required={required_mode}")
    if not ok:
        raise typer.Exit(1)
