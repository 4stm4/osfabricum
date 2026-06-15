"""M58 — Explain / Why Engine CLI commands."""

from __future__ import annotations

import typer

from osfabricum import explain as explain_svc
from osfabricum.db.session import sync_session
from osfabricum.settings import load_settings

explain_app = typer.Typer(help="Explain / Why engine")


def _db() -> str:
    return load_settings().database.url


@explain_app.command("kinds")
def list_kinds() -> None:
    """List explain trace kinds."""
    with sync_session(_db()) as s:
        kinds = explain_svc.list_explain_trace_kinds(s)
    for k in kinds:
        typer.echo(f"{k.kind:24s} {k.label}")


@explain_app.command("trace")
def add_trace(
    target_kind: str = typer.Option(..., "--target-kind"),
    target_key: str = typer.Option(..., "--target-key"),
    reason_kind: str = typer.Option(..., "--reason-kind"),
    reason_detail: str = typer.Option("", "--detail"),
    build_id: str | None = typer.Option(None, "--build-id"),
) -> None:
    """Record an explain trace."""
    with sync_session(_db()) as s:
        t = explain_svc.add_trace(
            s, target_kind=target_kind, target_key=target_key,
            reason_kind=reason_kind, reason_detail=reason_detail,
            build_id=build_id,
        )
        s.commit()
    typer.echo(f"Trace {t.id} recorded: {target_kind}/{target_key} ← {reason_kind}")


@explain_app.command("item")
def explain_item(
    target_key: str = typer.Argument(...),
    target_kind: str | None = typer.Option(None, "--kind"),
    build_id: str | None = typer.Option(None, "--build-id"),
) -> None:
    """Show why a specific item was included."""
    with sync_session(_db()) as s:
        traces = explain_svc.explain_item(s, target_key, target_kind, build_id)
        typer.echo(explain_svc.render_explain_text(traces))


@explain_app.command("build")
def explain_build(
    build_id: str = typer.Argument(...),
) -> None:
    """Show all explain traces for a build."""
    with sync_session(_db()) as s:
        traces = explain_svc.explain_build(s, build_id)
        typer.echo(explain_svc.render_explain_text(traces))
