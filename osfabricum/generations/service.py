"""Business logic for M60 — System Generations / Rollback Designer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    Generation,
    GenerationArtifact,
    RollbackKind,
    RollbackTarget,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_STATUSES: frozenset[str] = frozenset({"active", "archived", "rolled_back"})
VALID_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {"image", "rootfs", "bootloader", "kernel", "initramfs", "other"}
)
VALID_ROLLBACK_KINDS: frozenset[str] = frozenset(
    {"full", "partial", "config-only", "data-preserve"}
)


def list_rollback_kinds(session: "Session") -> list[RollbackKind]:
    return list(
        session.scalars(
            select(RollbackKind).order_by(RollbackKind.display_order)
        ).all()
    )


def create_generation(
    session: "Session",
    distribution_id: str,
    generation_number: int,
    description: str = "",
    release_id: str | None = None,
    status: str = "active",
) -> Generation:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}"
        )
    gen = Generation(
        id=_uuid(), distribution_id=distribution_id,
        release_id=release_id, generation_number=generation_number,
        status=status, description=description,
        rendered_generation_manifest=None, content_hash=None, rendered_at=None,
        created_at=_now(), updated_at=_now(),
    )
    session.add(gen)
    session.flush()
    return gen


def list_generations(
    session: "Session",
    distribution_id: str | None = None,
    status: str | None = None,
) -> list[Generation]:
    q = select(Generation).order_by(Generation.generation_number.desc())
    if distribution_id is not None:
        q = q.where(Generation.distribution_id == distribution_id)
    if status is not None:
        q = q.where(Generation.status == status)
    return list(session.scalars(q).all())


def get_generation(session: "Session", generation_id: str) -> Generation:
    g = session.get(Generation, generation_id)
    if g is None:
        raise KeyError(f"Generation {generation_id!r} not found")
    return g


def update_generation(
    session: "Session",
    generation_id: str,
    status: str | None = None,
    description: str | None = None,
) -> Generation:
    gen = get_generation(session, generation_id)
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}"
            )
        gen.status = status
    if description is not None:
        gen.description = description
    _invalidate(gen)
    gen.updated_at = _now()
    session.flush()
    return gen


def add_generation_artifact(
    session: "Session",
    generation_id: str,
    artifact_role: str,
    artifact_id: str | None = None,
    artifact_uri: str | None = None,
) -> GenerationArtifact:
    if artifact_role not in VALID_ARTIFACT_ROLES:
        raise ValueError(
            f"Invalid artifact_role {artifact_role!r}. "
            f"Valid: {sorted(VALID_ARTIFACT_ROLES)}"
        )
    existing = session.scalars(
        select(GenerationArtifact).where(
            GenerationArtifact.generation_id == generation_id,
            GenerationArtifact.artifact_role == artifact_role,
        )
    ).first()
    if existing is not None:
        existing.artifact_id = artifact_id
        existing.artifact_uri = artifact_uri
    else:
        existing = GenerationArtifact(
            id=_uuid(), generation_id=generation_id,
            artifact_role=artifact_role, artifact_id=artifact_id,
            artifact_uri=artifact_uri,
        )
        session.add(existing)

    gen = session.get(Generation, generation_id)
    if gen is not None:
        _invalidate(gen)
        gen.updated_at = _now()

    session.flush()
    return existing


def add_rollback_target(
    session: "Session",
    generation_id: str,
    target_generation_number: int,
    rollback_kind: str = "full",
    priority: int = 0,
) -> RollbackTarget:
    if rollback_kind not in VALID_ROLLBACK_KINDS:
        raise ValueError(
            f"Invalid rollback_kind {rollback_kind!r}. "
            f"Valid: {sorted(VALID_ROLLBACK_KINDS)}"
        )
    existing = session.scalars(
        select(RollbackTarget).where(
            RollbackTarget.generation_id == generation_id,
            RollbackTarget.target_generation_number == target_generation_number,
        )
    ).first()
    if existing is not None:
        existing.rollback_kind = rollback_kind
        existing.priority = priority
        existing.rendered_rollback_plan = None
    else:
        existing = RollbackTarget(
            id=_uuid(), generation_id=generation_id,
            target_generation_number=target_generation_number,
            rollback_kind=rollback_kind, priority=priority,
            rendered_rollback_plan=None, created_at=_now(),
        )
        session.add(existing)

    gen = session.get(Generation, generation_id)
    if gen is not None:
        _invalidate(gen)
        gen.updated_at = _now()

    session.flush()
    return existing


def render_generation_manifest(
    session: "Session", generation_id: str
) -> Generation:
    gen = get_generation(session, generation_id)
    artifacts = session.scalars(
        select(GenerationArtifact).where(
            GenerationArtifact.generation_id == generation_id
        ).order_by(GenerationArtifact.artifact_role)
    ).all()
    rollbacks = session.scalars(
        select(RollbackTarget).where(
            RollbackTarget.generation_id == generation_id
        ).order_by(RollbackTarget.priority, RollbackTarget.target_generation_number)
    ).all()

    lines = [
        "# OSFabricum Generation Manifest",
        f"# Generated for generation {gen.generation_number}",
        "",
        "[generation]",
        f"id                = {gen.id}",
        f"generation_number = {gen.generation_number}",
        f"status            = {gen.status}",
        f"distribution_id   = {gen.distribution_id or ''}",
        f"release_id        = {gen.release_id or ''}",
        f"description       = {gen.description}",
        "",
        "[artifacts]",
    ]
    for a in artifacts:
        lines.append(
            f"{a.artifact_role} = {a.artifact_uri or a.artifact_id or 'unset'}"
        )

    if rollbacks:
        lines.extend(["", "[rollback_targets]"])
        for r in rollbacks:
            lines.append(
                f"target_{r.target_generation_number} = {r.rollback_kind}"
                f" (priority={r.priority})"
            )

    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    gen.rendered_generation_manifest = rendered
    gen.content_hash = content_hash
    gen.rendered_at = datetime.utcnow()
    gen.updated_at = _now()
    session.flush()
    return gen


def render_rollback_plan(
    session: "Session",
    generation_id: str,
    target_generation_number: int,
) -> RollbackTarget:
    target = session.scalars(
        select(RollbackTarget).where(
            RollbackTarget.generation_id == generation_id,
            RollbackTarget.target_generation_number == target_generation_number,
        )
    ).first()
    if target is None:
        raise KeyError(
            f"RollbackTarget gen={generation_id!r} "
            f"target={target_generation_number!r} not found"
        )
    gen = get_generation(session, generation_id)
    lines = [
        "# OSFabricum Rollback Plan",
        f"# From generation {gen.generation_number} → {target_generation_number}",
        "",
        "[rollback]",
        f"source_generation = {gen.generation_number}",
        f"target_generation = {target_generation_number}",
        f"rollback_kind     = {target.rollback_kind}",
        f"priority          = {target.priority}",
        "",
        "[steps]",
    ]
    if target.rollback_kind == "full":
        lines += [
            "1 = stop all services",
            "2 = restore rootfs from target generation snapshot",
            "3 = restore bootloader if changed",
            "4 = start services",
        ]
    elif target.rollback_kind == "config-only":
        lines += [
            "1 = diff config files between generations",
            "2 = restore changed config files only",
            "3 = reload affected services",
        ]
    elif target.rollback_kind == "data-preserve":
        lines += [
            "1 = preserve user data partition",
            "2 = restore OS partition to target generation",
            "3 = reboot",
        ]
    else:
        lines += ["1 = perform partial rollback as defined by operator"]

    rendered = "\n".join(lines) + "\n"
    target.rendered_rollback_plan = rendered
    session.flush()
    return target


def _invalidate(gen: Generation) -> None:
    gen.content_hash = None
    gen.rendered_at = None
    gen.rendered_generation_manifest = None
