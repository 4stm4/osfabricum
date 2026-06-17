"""Business logic for M65 — Size / Footprint Optimizer."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import SizeBudget, SizeBudgetKind, SizeReport, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_BUDGET_KINDS: frozenset[str] = frozenset(
    {"image", "rootfs", "package-set", "kernel", "initramfs", "apps"}
)


def list_size_budget_kinds(session: "Session") -> list[SizeBudgetKind]:
    return list(
        session.scalars(
            select(SizeBudgetKind).order_by(SizeBudgetKind.display_order)
        ).all()
    )


def set_size_budget(
    session: "Session",
    profile_id: str,
    budget_kind: str,
    budget_bytes: int,
    is_hard_limit: bool = False,
) -> SizeBudget:
    if budget_kind not in VALID_BUDGET_KINDS:
        raise ValueError(
            f"Invalid budget_kind {budget_kind!r}. Valid: {sorted(VALID_BUDGET_KINDS)}"
        )
    existing = session.scalars(
        select(SizeBudget).where(
            SizeBudget.profile_id == profile_id,
            SizeBudget.budget_kind == budget_kind,
        )
    ).first()
    if existing is not None:
        existing.budget_bytes = budget_bytes
        existing.is_hard_limit = is_hard_limit
    else:
        existing = SizeBudget(
            id=_uuid(), profile_id=profile_id, budget_kind=budget_kind,
            budget_bytes=budget_bytes, is_hard_limit=is_hard_limit, created_at=_now(),
        )
        session.add(existing)
    session.flush()
    return existing


def list_size_budgets(
    session: "Session", profile_id: str | None = None
) -> list[SizeBudget]:
    q = select(SizeBudget).order_by(SizeBudget.budget_kind)
    if profile_id is not None:
        q = q.where(SizeBudget.profile_id == profile_id)
    return list(session.scalars(q).all())


def analyze_size(
    session: "Session",
    build_id: str | None = None,
    profile_id: str | None = None,
    size_data: dict | None = None,
) -> SizeReport:
    data = size_data or {}
    budgets: list[SizeBudget] = []
    if profile_id is not None:
        budgets = list_size_budgets(session, profile_id)

    lines = [
        "# OSFabricum Size Report",
        f"# build_id  = {build_id or 'N/A'}",
        f"# profile_id = {profile_id or 'N/A'}",
        "",
        "[sizes]",
    ]
    for kind, value in sorted(data.items()):
        lines.append(f"{kind:20s} = {value} bytes")

    if budgets:
        lines.extend(["", "[budget_check]"])
        violations: list[str] = []
        for b in budgets:
            actual = data.get(b.budget_kind, 0)
            status = "ok"
            if actual > b.budget_bytes:
                status = "EXCEEDED" if b.is_hard_limit else "warning"
                violations.append(
                    f"{b.budget_kind}: {actual} > {b.budget_bytes}"
                )
            lines.append(
                f"{b.budget_kind:20s} = {actual}/{b.budget_bytes} [{status}]"
            )
        if violations:
            lines.extend(["", "[violations]"])
            for v in violations:
                lines.append(f"  ! {v}")

    suggestions: list[str] = []
    if data.get("rootfs", 0) > 100 * 1024 * 1024:
        suggestions.append("Consider stripping debug symbols (--strip-all)")
    if data.get("image", 0) > 50 * 1024 * 1024:
        suggestions.append("Consider zstd compression for the image")

    if suggestions:
        lines.extend(["", "[suggestions]"])
        for s in suggestions:
            lines.append(f"  > {s}")

    rendered = "\n".join(lines) + "\n"
    summary = {
        "sizes": data,
        "budget_count": len(budgets),
        "build_id": build_id,
    }
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    report = SizeReport(
        id=_uuid(), build_id=build_id, profile_id=profile_id,
        rendered_report=rendered, summary_json=json.dumps(summary),
        content_hash=content_hash, created_at=_now(),
    )
    session.add(report)
    session.flush()
    return report


def list_size_reports(
    session: "Session",
    build_id: str | None = None,
    profile_id: str | None = None,
) -> list[SizeReport]:
    q = select(SizeReport).order_by(SizeReport.created_at.desc())
    if build_id is not None:
        q = q.where(SizeReport.build_id == build_id)
    if profile_id is not None:
        q = q.where(SizeReport.profile_id == profile_id)
    return list(session.scalars(q).all())
