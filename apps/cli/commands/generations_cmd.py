"""M60 — System Generations / Rollback Designer CLI commands."""

from __future__ import annotations

import typer

from osfabricum import generations as gen_svc
from osfabricum.db.session import sync_session
from osfabricum.settings import load_settings

generations_app = typer.Typer(help="System generations and rollback designer")


def _db() -> str:
    return load_settings().database.url


@generations_app.command("kinds")
def list_rollback_kinds() -> None:
    """List rollback kinds."""
    with sync_session(_db()) as s:
        kinds = gen_svc.list_rollback_kinds(s)
    for k in kinds:
        typer.echo(f"{k.kind:16s} {k.label}")


@generations_app.command("create")
def create_generation(
    distribution_id: str = typer.Option(..., "--dist"),
    generation_number: int = typer.Option(..., "--num"),
    description: str = typer.Option("", "--description"),
    status: str = typer.Option("active", "--status"),
) -> None:
    """Create a new generation record."""
    with sync_session(_db()) as s:
        g = gen_svc.create_generation(
            s, distribution_id=distribution_id,
            generation_number=generation_number,
            description=description, status=status,
        )
        s.commit()
    typer.echo(f"Generation {g.id}  num={g.generation_number}  status={g.status}")


@generations_app.command("list")
def list_generations(
    distribution_id: str | None = typer.Option(None, "--dist"),
    status: str | None = typer.Option(None, "--status"),
) -> None:
    """List generations."""
    with sync_session(_db()) as s:
        gens = gen_svc.list_generations(s, distribution_id, status)
    for g in gens:
        typer.echo(
            f"{g.id}  gen#{g.generation_number:4d}  {g.status:12s}  {g.description or ''}"
        )


@generations_app.command("artifact")
def add_artifact(
    generation_id: str = typer.Option(..., "--gen"),
    artifact_role: str = typer.Option(..., "--role"),
    artifact_uri: str | None = typer.Option(None, "--uri"),
    artifact_id: str | None = typer.Option(None, "--artifact-id"),
) -> None:
    """Add or update an artifact for a generation."""
    with sync_session(_db()) as s:
        a = gen_svc.add_generation_artifact(
            s, generation_id, artifact_role, artifact_id, artifact_uri
        )
        s.commit()
    typer.echo(f"Artifact {a.id}  role={a.artifact_role}  uri={a.artifact_uri}")


@generations_app.command("rollback-target")
def add_rollback_target(
    generation_id: str = typer.Option(..., "--gen"),
    target_num: int = typer.Option(..., "--target-num"),
    rollback_kind: str = typer.Option("full", "--kind"),
    priority: int = typer.Option(0, "--priority"),
) -> None:
    """Add a rollback target for a generation."""
    with sync_session(_db()) as s:
        t = gen_svc.add_rollback_target(
            s, generation_id, target_num, rollback_kind, priority
        )
        s.commit()
    typer.echo(f"RollbackTarget {t.id}  → gen#{t.target_generation_number}  kind={t.rollback_kind}")


@generations_app.command("render")
def render_manifest(
    generation_id: str = typer.Argument(...),
) -> None:
    """Render generation manifest."""
    with sync_session(_db()) as s:
        g = gen_svc.render_generation_manifest(s, generation_id)
        s.commit()
    typer.echo(g.rendered_generation_manifest)


@generations_app.command("rollback-plan")
def rollback_plan(
    generation_id: str = typer.Argument(...),
    target_num: int = typer.Option(..., "--target-num"),
) -> None:
    """Render rollback plan."""
    with sync_session(_db()) as s:
        t = gen_svc.render_rollback_plan(s, generation_id, target_num)
        s.commit()
    typer.echo(t.rendered_rollback_plan)
