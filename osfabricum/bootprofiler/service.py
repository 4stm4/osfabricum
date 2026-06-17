"""Business logic for M66 — Boot / Performance Profiler."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import BootProfile, BootSample, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_CAPTURE_METHODS: frozenset[str] = frozenset({"qemu", "serial", "journal"})
VALID_EVENT_KINDS: frozenset[str] = frozenset(
    {"kernel-init", "service-start", "userspace", "target-reached"}
)


def create_boot_profile(
    session: "Session",
    build_id: str | None = None,
    capture_method: str = "qemu",
) -> BootProfile:
    if capture_method not in VALID_CAPTURE_METHODS:
        raise ValueError(
            f"Invalid capture_method {capture_method!r}. "
            f"Valid: {sorted(VALID_CAPTURE_METHODS)}"
        )
    bp = BootProfile(
        id=_uuid(), build_id=build_id, capture_method=capture_method,
        total_boot_ms=None, rendered_timeline=None, summary_json=None,
        content_hash=None, created_at=_now(),
    )
    session.add(bp)
    session.flush()
    return bp


def add_boot_sample(
    session: "Session",
    boot_profile_id: str,
    event_kind: str,
    event_name: str,
    timestamp_ms: int,
    duration_ms: int | None = None,
    is_critical_path: bool = False,
) -> BootSample:
    if event_kind not in VALID_EVENT_KINDS:
        raise ValueError(
            f"Invalid event_kind {event_kind!r}. Valid: {sorted(VALID_EVENT_KINDS)}"
        )
    sample = BootSample(
        id=_uuid(), boot_profile_id=boot_profile_id,
        event_kind=event_kind, event_name=event_name,
        timestamp_ms=timestamp_ms, duration_ms=duration_ms,
        is_critical_path=is_critical_path,
    )
    session.add(sample)
    bp = session.get(BootProfile, boot_profile_id)
    if bp is not None:
        bp.content_hash = None
    session.flush()
    return sample


def list_boot_samples(
    session: "Session", boot_profile_id: str
) -> list[BootSample]:
    return list(
        session.scalars(
            select(BootSample)
            .where(BootSample.boot_profile_id == boot_profile_id)
            .order_by(BootSample.timestamp_ms)
        ).all()
    )


def list_boot_profiles(
    session: "Session", build_id: str | None = None
) -> list[BootProfile]:
    q = select(BootProfile).order_by(BootProfile.created_at.desc())
    if build_id is not None:
        q = q.where(BootProfile.build_id == build_id)
    return list(session.scalars(q).all())


def get_boot_profile(session: "Session", profile_id: str) -> BootProfile:
    bp = session.get(BootProfile, profile_id)
    if bp is None:
        raise KeyError(f"BootProfile {profile_id!r} not found")
    return bp


def render_boot_timeline(session: "Session", profile_id: str) -> BootProfile:
    bp = get_boot_profile(session, profile_id)
    samples = list_boot_samples(session, profile_id)

    total_ms = max((s.timestamp_ms + (s.duration_ms or 0) for s in samples), default=0)
    bp.total_boot_ms = total_ms

    lines = [
        "# OSFabricum Boot Timeline",
        f"# build_id       = {bp.build_id or 'N/A'}",
        f"# capture_method = {bp.capture_method}",
        f"# total_boot_ms  = {total_ms}",
        "",
        "[timeline]",
    ]
    critical = [s for s in samples if s.is_critical_path]
    others = [s for s in samples if not s.is_critical_path]

    for s in samples:
        dur = f"+{s.duration_ms}ms" if s.duration_ms else ""
        crit = " *" if s.is_critical_path else ""
        lines.append(f"  {s.timestamp_ms:6d}ms  {s.event_kind:16s}  {s.event_name}{dur}{crit}")

    if critical:
        lines.extend(["", "[critical_path]"])
        for s in critical:
            lines.append(f"  {s.timestamp_ms:6d}ms  {s.event_name}")

    summary = {
        "total_boot_ms": total_ms,
        "sample_count": len(samples),
        "critical_path_steps": len(critical),
        "build_id": bp.build_id,
    }
    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    bp.rendered_timeline = rendered
    bp.summary_json = json.dumps(summary)
    bp.content_hash = content_hash
    session.flush()
    return bp
