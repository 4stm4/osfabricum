"""Business logic for M56 — Patch Queue / Source Patch Manager."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    Patch,
    PatchApplicationResult,
    PatchSet,
    PatchTargetKind,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_TARGET_KINDS: frozenset[str] = frozenset(
    {"kernel", "package-source", "branding", "config-template", "build-recipe"}
)
VALID_FORMATS: frozenset[str] = frozenset({"diff", "quilt", "git-am"})
VALID_STATUSES: frozenset[str] = frozenset({"pending", "success", "failed", "partial"})


def list_patch_target_kinds(session: "Session") -> list[PatchTargetKind]:
    return list(
        session.scalars(
            select(PatchTargetKind).order_by(PatchTargetKind.display_order)
        ).all()
    )


def create_patch_set(
    session: "Session",
    name: str,
    distribution_id: str | None = None,
    description: str = "",
    target_kind: str = "kernel",
) -> PatchSet:
    if target_kind not in VALID_TARGET_KINDS:
        raise ValueError(
            f"Invalid target_kind {target_kind!r}. Valid: {sorted(VALID_TARGET_KINDS)}"
        )
    existing = session.scalar(
        select(PatchSet).where(
            PatchSet.distribution_id == distribution_id,
            PatchSet.name == name,
        )
    )
    if existing is not None:
        raise ValueError(
            f"Patch set {name!r} already exists for distribution {distribution_id!r}"
        )
    now = _now()
    ps = PatchSet(
        id=_uuid(), name=name, distribution_id=distribution_id,
        description=description, target_kind=target_kind,
        created_at=now, updated_at=now,
    )
    session.add(ps)
    session.flush()
    return ps


def list_patch_sets(
    session: "Session", distribution_id: str | None = None
) -> list[PatchSet]:
    q = select(PatchSet).order_by(PatchSet.name)
    if distribution_id is not None:
        q = q.where(PatchSet.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_patch_set(session: "Session", patch_set_id: str) -> PatchSet:
    ps = session.get(PatchSet, patch_set_id)
    if ps is None:
        raise KeyError(f"Patch set {patch_set_id!r} not found")
    return ps


def update_patch_set(
    session: "Session", patch_set_id: str, **kwargs: object
) -> PatchSet:
    ps = get_patch_set(session, patch_set_id)
    for k, v in kwargs.items():
        setattr(ps, k, v)
    ps.updated_at = _now()
    _invalidate(session, patch_set_id)
    session.flush()
    return ps


def add_patch(
    session: "Session",
    patch_set_id: str,
    sequence_num: int,
    name: str,
    patch_content: str = "",
    patch_format: str = "diff",
    is_enabled: bool = True,
    description: str = "",
) -> Patch:
    if patch_format not in VALID_FORMATS:
        raise ValueError(
            f"Invalid patch_format {patch_format!r}. Valid: {sorted(VALID_FORMATS)}"
        )
    get_patch_set(session, patch_set_id)
    existing = session.scalar(
        select(Patch).where(
            Patch.patch_set_id == patch_set_id,
            Patch.sequence_num == sequence_num,
        )
    )
    if existing is not None:
        existing.name = name
        existing.patch_content = patch_content
        existing.patch_format = patch_format
        existing.is_enabled = is_enabled
        existing.description = description
        _invalidate(session, patch_set_id)
        session.flush()
        return existing
    p = Patch(
        id=_uuid(), patch_set_id=patch_set_id, sequence_num=sequence_num,
        name=name, patch_content=patch_content, patch_format=patch_format,
        is_enabled=is_enabled, description=description,
    )
    session.add(p)
    _invalidate(session, patch_set_id)
    session.flush()
    return p


def list_patches(session: "Session", patch_set_id: str) -> list[Patch]:
    get_patch_set(session, patch_set_id)
    return list(
        session.scalars(
            select(Patch)
            .where(Patch.patch_set_id == patch_set_id)
            .order_by(Patch.sequence_num)
        ).all()
    )


def render_patch_manifest(session: "Session", patch_set_id: str) -> PatchSet:
    ps = get_patch_set(session, patch_set_id)
    patches = list_patches(session, patch_set_id)
    manifest = _render_manifest(ps, patches)
    content_hash = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
    ps.rendered_patch_manifest = manifest
    ps.content_hash = content_hash
    ps.rendered_at = datetime.utcnow()
    session.flush()
    return ps


def record_application(
    session: "Session",
    patch_set_id: str,
    status: str = "success",
    applied_count: int = 0,
    failed_at_sequence: int | None = None,
    error_message: str | None = None,
) -> PatchApplicationResult:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}"
        )
    get_patch_set(session, patch_set_id)
    result = PatchApplicationResult(
        id=_uuid(), patch_set_id=patch_set_id,
        applied_at=_now(), status=status,
        applied_count=applied_count,
        failed_at_sequence=failed_at_sequence,
        error_message=error_message,
    )
    session.add(result)
    session.flush()
    return result


def list_application_results(
    session: "Session", patch_set_id: str
) -> list[PatchApplicationResult]:
    get_patch_set(session, patch_set_id)
    return list(
        session.scalars(
            select(PatchApplicationResult)
            .where(PatchApplicationResult.patch_set_id == patch_set_id)
            .order_by(PatchApplicationResult.applied_at.desc())
        ).all()
    )


def _render_manifest(ps: PatchSet, patches: list[Patch]) -> str:
    lines = [
        f"# OSFabricum Patch Manifest — {ps.name}",
        f"# target: {ps.target_kind}",
        "",
        "[patch_set]",
        f"name = {ps.name}",
        f"target_kind = {ps.target_kind}",
        "",
    ]
    enabled = [p for p in patches if p.is_enabled]
    disabled = [p for p in patches if not p.is_enabled]

    lines.append(f"[patches]  # {len(enabled)} enabled, {len(disabled)} disabled")
    if enabled:
        for p in enabled:
            lines.append(
                f"  seq={p.sequence_num:04d}  [{p.patch_format:6s}]  {p.name}"
            )
    else:
        lines.append("  # No enabled patches")

    if disabled:
        lines.append("")
        lines.append("[disabled_patches]")
        for p in disabled:
            lines.append(f"  seq={p.sequence_num:04d}  {p.name}  (disabled)")

    return "\n".join(lines) + "\n"


def _invalidate(session: "Session", patch_set_id: str) -> None:
    ps = session.get(PatchSet, patch_set_id)
    if ps is not None:
        ps.content_hash = None
        ps.rendered_at = None
