"""Business logic for M55 — Override / Masking engine."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import OverrideKind, OverrideProfile, OverrideRule, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_ACTIONS: frozenset[str] = frozenset(
    {"set", "unset", "mask", "append", "prepend", "replace"}
)
VALID_TARGET_TYPES: frozenset[str] = frozenset(
    {"package", "config", "kernel-param", "service", "sysctl"}
)


def list_override_kinds(session: "Session") -> list[OverrideKind]:
    return list(
        session.scalars(select(OverrideKind).order_by(OverrideKind.display_order)).all()
    )


def create_override_profile(
    session: "Session",
    name: str,
    distribution_id: str | None = None,
    description: str = "",
) -> OverrideProfile:
    existing = session.scalar(
        select(OverrideProfile).where(
            OverrideProfile.distribution_id == distribution_id,
            OverrideProfile.name == name,
        )
    )
    if existing is not None:
        raise ValueError(
            f"Override profile {name!r} already exists for distribution {distribution_id!r}"
        )
    now = _now()
    p = OverrideProfile(
        id=_uuid(), name=name, distribution_id=distribution_id,
        description=description, created_at=now, updated_at=now,
    )
    session.add(p)
    session.flush()
    return p


def list_override_profiles(
    session: "Session", distribution_id: str | None = None
) -> list[OverrideProfile]:
    q = select(OverrideProfile).order_by(OverrideProfile.name)
    if distribution_id is not None:
        q = q.where(OverrideProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_override_profile(session: "Session", profile_id: str) -> OverrideProfile:
    p = session.get(OverrideProfile, profile_id)
    if p is None:
        raise KeyError(f"Override profile {profile_id!r} not found")
    return p


def update_override_profile(
    session: "Session", profile_id: str, **kwargs: object
) -> OverrideProfile:
    p = get_override_profile(session, profile_id)
    for k, v in kwargs.items():
        setattr(p, k, v)
    p.updated_at = _now()
    _invalidate(session, profile_id)
    session.flush()
    return p


def add_override_rule(
    session: "Session",
    profile_id: str,
    target_type: str,
    target_key: str,
    action: str = "set",
    value: str | None = None,
    reason: str = "",
    priority: int = 0,
) -> OverrideRule:
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"Invalid action {action!r}. Valid: {sorted(VALID_ACTIONS)}"
        )
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(
            f"Invalid target_type {target_type!r}. Valid: {sorted(VALID_TARGET_TYPES)}"
        )
    get_override_profile(session, profile_id)
    existing = session.scalar(
        select(OverrideRule).where(
            OverrideRule.profile_id == profile_id,
            OverrideRule.target_type == target_type,
            OverrideRule.target_key == target_key,
        )
    )
    if existing is not None:
        existing.action = action
        existing.value = value
        existing.reason = reason
        existing.priority = priority
        _invalidate(session, profile_id)
        session.flush()
        return existing
    rule = OverrideRule(
        id=_uuid(), profile_id=profile_id, target_type=target_type,
        target_key=target_key, action=action, value=value,
        reason=reason, priority=priority,
    )
    session.add(rule)
    _invalidate(session, profile_id)
    session.flush()
    return rule


def list_override_rules(
    session: "Session",
    profile_id: str,
    target_type: str | None = None,
) -> list[OverrideRule]:
    get_override_profile(session, profile_id)
    q = (
        select(OverrideRule)
        .where(OverrideRule.profile_id == profile_id)
        .order_by(OverrideRule.target_type, OverrideRule.priority, OverrideRule.target_key)
    )
    if target_type is not None:
        q = q.where(OverrideRule.target_type == target_type)
    return list(session.scalars(q).all())


def render_override_policy(session: "Session", profile_id: str) -> OverrideProfile:
    p = get_override_profile(session, profile_id)
    rules = list_override_rules(session, profile_id)
    policy = _render_policy(p, rules)
    content_hash = "sha256:" + hashlib.sha256(policy.encode()).hexdigest()
    p.rendered_override_policy = policy
    p.content_hash = content_hash
    p.rendered_at = datetime.utcnow()
    session.flush()
    return p


def _render_policy(profile: OverrideProfile, rules: list[OverrideRule]) -> str:
    lines = [
        f"# OSFabricum Override Policy — {profile.name}",
        "",
        "[override_policy]",
        f"profile = {profile.name}",
        f"total_rules = {len(rules)}",
        "",
    ]
    by_type: dict[str, list[OverrideRule]] = {}
    for r in rules:
        by_type.setdefault(r.target_type, []).append(r)

    for ttype in sorted(by_type):
        lines.append(f"[{ttype}]")
        for r in by_type[ttype]:
            val_part = f" = {r.value}" if r.value is not None else ""
            reason_part = f"  # {r.reason}" if r.reason else ""
            lines.append(
                f"  prio={r.priority:3d}  {r.action:8s}  {r.target_key}{val_part}{reason_part}"
            )
        lines.append("")

    if not rules:
        lines.append("# No override rules defined")

    return "\n".join(lines) + "\n"


def _invalidate(session: "Session", profile_id: str) -> None:
    p = session.get(OverrideProfile, profile_id)
    if p is not None:
        p.content_hash = None
        p.rendered_at = None
