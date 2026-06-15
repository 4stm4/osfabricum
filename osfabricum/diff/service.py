"""Business logic for M59 — Build / Profile / Release Diff."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import DiffReport, DiffReportKind, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_ENTITY_KINDS: frozenset[str] = frozenset({"profile", "build", "release"})
VALID_DIFF_KINDS: frozenset[str] = frozenset(
    {"package", "kernel-config", "service", "filesystem", "sbom", "size", "hash"}
)


def list_diff_report_kinds(session: "Session") -> list[DiffReportKind]:
    return list(
        session.scalars(
            select(DiffReportKind).order_by(DiffReportKind.display_order)
        ).all()
    )


def list_diff_reports(
    session: "Session",
    entity_kind: str | None = None,
    entity_a_id: str | None = None,
    entity_b_id: str | None = None,
) -> list[DiffReport]:
    q = select(DiffReport).order_by(DiffReport.created_at.desc())
    if entity_kind is not None:
        q = q.where(DiffReport.entity_kind == entity_kind)
    if entity_a_id is not None:
        q = q.where(DiffReport.entity_a_id == entity_a_id)
    if entity_b_id is not None:
        q = q.where(DiffReport.entity_b_id == entity_b_id)
    return list(session.scalars(q).all())


def get_diff_report(session: "Session", report_id: str) -> DiffReport:
    r = session.get(DiffReport, report_id)
    if r is None:
        raise KeyError(f"DiffReport {report_id!r} not found")
    return r


def create_diff_report(
    session: "Session",
    entity_kind: str,
    entity_a_id: str,
    entity_b_id: str,
    diff_kind: str = "package",
    context: dict | None = None,
) -> DiffReport:
    if entity_kind not in VALID_ENTITY_KINDS:
        raise ValueError(
            f"Invalid entity_kind {entity_kind!r}. Valid: {sorted(VALID_ENTITY_KINDS)}"
        )
    if diff_kind not in VALID_DIFF_KINDS:
        raise ValueError(
            f"Invalid diff_kind {diff_kind!r}. Valid: {sorted(VALID_DIFF_KINDS)}"
        )
    report = DiffReport(
        id=_uuid(), entity_kind=entity_kind,
        entity_a_id=entity_a_id, entity_b_id=entity_b_id,
        rendered_diff=None, summary_json=None, content_hash=None,
        created_at=_now(),
    )
    session.add(report)
    session.flush()
    return report


def render_diff_report(
    session: "Session",
    report_id: str,
    a_data: dict | None = None,
    b_data: dict | None = None,
) -> DiffReport:
    report = get_diff_report(session, report_id)
    import json

    a = a_data or {}
    b = b_data or {}

    all_keys = sorted(set(list(a.keys()) + list(b.keys())))
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    for k in all_keys:
        if k not in a:
            added.append(k)
        elif k not in b:
            removed.append(k)
        elif a[k] != b[k]:
            changed.append(k)

    lines = [
        "# OSFabricum Diff Report",
        f"# {report.entity_kind}: {report.entity_a_id} → {report.entity_b_id}",
        "",
        "[summary]",
        f"added   = {len(added)}",
        f"removed = {len(removed)}",
        f"changed = {len(changed)}",
    ]
    if added:
        lines.extend(["", "[added]"])
        for k in added:
            lines.append(f"+ {k} = {b[k]}")
    if removed:
        lines.extend(["", "[removed]"])
        for k in removed:
            lines.append(f"- {k} = {a[k]}")
    if changed:
        lines.extend(["", "[changed]"])
        for k in changed:
            lines.append(f"  {k}: {a[k]!r} → {b[k]!r}")

    rendered = "\n".join(lines) + "\n"
    summary = {"added": len(added), "removed": len(removed), "changed": len(changed)}
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()

    report.rendered_diff = rendered
    report.summary_json = json.dumps(summary)
    report.content_hash = content_hash
    session.flush()
    return report
