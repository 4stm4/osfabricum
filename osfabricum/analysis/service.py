"""Business logic for M64 — Build Analysis Dashboard."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import BuildAnalysis, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_ANALYSIS_KINDS: frozenset[str] = frozenset(
    {"time", "size", "critical-path", "cache", "warnings"}
)


def list_build_analyses(
    session: "Session",
    build_id: str | None = None,
    analysis_kind: str | None = None,
) -> list[BuildAnalysis]:
    q = select(BuildAnalysis).order_by(BuildAnalysis.created_at.desc())
    if build_id is not None:
        q = q.where(BuildAnalysis.build_id == build_id)
    if analysis_kind is not None:
        q = q.where(BuildAnalysis.analysis_kind == analysis_kind)
    return list(session.scalars(q).all())


def get_build_analysis(session: "Session", analysis_id: str) -> BuildAnalysis:
    a = session.get(BuildAnalysis, analysis_id)
    if a is None:
        raise KeyError(f"BuildAnalysis {analysis_id!r} not found")
    return a


def analyze_build(
    session: "Session",
    build_id: str | None,
    analysis_kind: str = "time",
    input_data: dict | None = None,
) -> BuildAnalysis:
    if analysis_kind not in VALID_ANALYSIS_KINDS:
        raise ValueError(
            f"Invalid analysis_kind {analysis_kind!r}. "
            f"Valid: {sorted(VALID_ANALYSIS_KINDS)}"
        )
    data = input_data or {}
    lines = [
        "# OSFabricum Build Analysis",
        f"# kind = {analysis_kind}",
        f"# build_id = {build_id or 'N/A'}",
        "",
        f"[{analysis_kind}]",
    ]
    summary: dict = {"kind": analysis_kind, "build_id": build_id}

    if analysis_kind == "time":
        total_s = data.get("total_seconds", 0)
        lines += [
            f"total_seconds     = {total_s}",
            f"slowest_task      = {data.get('slowest_task', 'N/A')}",
            f"slowest_task_s    = {data.get('slowest_task_s', 0)}",
        ]
        summary.update({"total_seconds": total_s})

    elif analysis_kind == "size":
        image_mb = data.get("image_mb", 0)
        rootfs_mb = data.get("rootfs_mb", 0)
        lines += [
            f"image_mb          = {image_mb}",
            f"rootfs_mb         = {rootfs_mb}",
            f"largest_package   = {data.get('largest_package', 'N/A')}",
        ]
        summary.update({"image_mb": image_mb, "rootfs_mb": rootfs_mb})

    elif analysis_kind == "critical-path":
        path = data.get("path", [])
        lines.append(f"critical_path_len = {len(path)}")
        for step in path:
            lines.append(f"  - {step}")
        summary.update({"critical_path_len": len(path)})

    elif analysis_kind == "cache":
        hits = data.get("hits", 0)
        misses = data.get("misses", 0)
        total = hits + misses
        pct = round(100 * hits / total, 1) if total else 0
        lines += [
            f"cache_hits        = {hits}",
            f"cache_misses      = {misses}",
            f"cache_hit_pct     = {pct}%",
        ]
        summary.update({"hits": hits, "misses": misses, "hit_pct": pct})

    elif analysis_kind == "warnings":
        warnings = data.get("warnings", [])
        lines.append(f"warning_count     = {len(warnings)}")
        for w in warnings[:20]:
            lines.append(f"  - {w}")
        summary.update({"warning_count": len(warnings)})

    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    analysis = BuildAnalysis(
        id=_uuid(), build_id=build_id, analysis_kind=analysis_kind,
        rendered_report=rendered, summary_json=json.dumps(summary),
        content_hash=content_hash, created_at=_now(),
    )
    session.add(analysis)
    session.flush()
    return analysis
