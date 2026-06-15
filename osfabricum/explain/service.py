"""Business logic for M58 — Explain / Why Engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import ExplainTrace, ExplainTraceKind, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_TARGET_KINDS: frozenset[str] = frozenset(
    {"package", "config", "driver", "service", "firmware", "kernel"}
)
VALID_REASON_KINDS: frozenset[str] = frozenset(
    {"profile-explicit", "group", "dependency", "driver",
     "security", "layer", "override"}
)


def list_explain_trace_kinds(session: "Session") -> list[ExplainTraceKind]:
    return list(
        session.scalars(
            select(ExplainTraceKind).order_by(ExplainTraceKind.display_order)
        ).all()
    )


def add_trace(
    session: "Session",
    target_kind: str,
    target_key: str,
    reason_kind: str,
    reason_detail: str = "",
    build_id: str | None = None,
    source_id: str | None = None,
) -> ExplainTrace:
    if target_kind not in VALID_TARGET_KINDS:
        raise ValueError(
            f"Invalid target_kind {target_kind!r}. Valid: {sorted(VALID_TARGET_KINDS)}"
        )
    if reason_kind not in VALID_REASON_KINDS:
        raise ValueError(
            f"Invalid reason_kind {reason_kind!r}. Valid: {sorted(VALID_REASON_KINDS)}"
        )
    trace = ExplainTrace(
        id=_uuid(), build_id=build_id,
        target_kind=target_kind, target_key=target_key,
        reason_kind=reason_kind, reason_detail=reason_detail,
        source_id=source_id, created_at=_now(),
    )
    session.add(trace)
    session.flush()
    return trace


def explain_item(
    session: "Session",
    target_key: str,
    target_kind: str | None = None,
    build_id: str | None = None,
) -> list[ExplainTrace]:
    q = select(ExplainTrace).where(ExplainTrace.target_key == target_key)
    if target_kind is not None:
        q = q.where(ExplainTrace.target_kind == target_kind)
    if build_id is not None:
        q = q.where(ExplainTrace.build_id == build_id)
    q = q.order_by(ExplainTrace.created_at)
    return list(session.scalars(q).all())


def explain_build(session: "Session", build_id: str) -> list[ExplainTrace]:
    return list(
        session.scalars(
            select(ExplainTrace)
            .where(ExplainTrace.build_id == build_id)
            .order_by(ExplainTrace.target_kind, ExplainTrace.target_key)
        ).all()
    )


def list_traces(
    session: "Session",
    build_id: str | None = None,
    target_kind: str | None = None,
    reason_kind: str | None = None,
) -> list[ExplainTrace]:
    q = select(ExplainTrace).order_by(
        ExplainTrace.target_kind, ExplainTrace.target_key
    )
    if build_id is not None:
        q = q.where(ExplainTrace.build_id == build_id)
    if target_kind is not None:
        q = q.where(ExplainTrace.target_kind == target_kind)
    if reason_kind is not None:
        q = q.where(ExplainTrace.reason_kind == reason_kind)
    return list(session.scalars(q).all())


def render_explain_text(traces: list[ExplainTrace]) -> str:
    if not traces:
        return "No explain traces found.\n"
    lines = ["# OSFabricum Explain Trace", ""]
    by_target: dict[str, list[ExplainTrace]] = {}
    for t in traces:
        key = f"{t.target_kind}:{t.target_key}"
        by_target.setdefault(key, []).append(t)

    for key in sorted(by_target):
        lines.append(f"[{key}]")
        for t in by_target[key]:
            build_part = f"  build={t.build_id}" if t.build_id else ""
            lines.append(
                f"  reason = {t.reason_kind}{build_part}"
            )
            if t.reason_detail:
                lines.append(f"  detail = {t.reason_detail}")
        lines.append("")

    return "\n".join(lines)
