"""Business logic for M51 — Cache / Mirror / Offline designer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    CachePolicyKind,
    CachePriorityRule,
    MirrorEndpoint,
    MirrorProfile,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_CACHE_POLICIES: frozenset[str] = frozenset(
    {"always", "prefer", "bypass", "offline-only"}
)

# ---------------------------------------------------------------------------
# Cache policy kinds
# ---------------------------------------------------------------------------


def list_cache_policy_kinds(session: "Session") -> list[CachePolicyKind]:
    return list(
        session.scalars(
            select(CachePolicyKind).order_by(CachePolicyKind.display_order)
        ).all()
    )


# ---------------------------------------------------------------------------
# Mirror profiles — CRUD
# ---------------------------------------------------------------------------


def create_mirror_profile(
    session: "Session",
    name: str,
    distribution_id: str | None = None,
    description: str = "",
    offline_mode: bool = False,
    max_cache_size_mb: int | None = None,
    cache_ttl_days: int = 7,
) -> MirrorProfile:
    existing = session.scalar(
        select(MirrorProfile).where(
            MirrorProfile.distribution_id == distribution_id,
            MirrorProfile.name == name,
        )
    )
    if existing is not None:
        raise ValueError(
            f"Mirror profile {name!r} already exists for distribution {distribution_id!r}"
        )
    now = _now()
    p = MirrorProfile(
        id=_uuid(),
        name=name,
        distribution_id=distribution_id,
        description=description,
        offline_mode=offline_mode,
        max_cache_size_mb=max_cache_size_mb,
        cache_ttl_days=cache_ttl_days,
        created_at=now,
        updated_at=now,
    )
    session.add(p)
    session.flush()
    return p


def list_mirror_profiles(
    session: "Session",
    distribution_id: str | None = None,
) -> list[MirrorProfile]:
    q = select(MirrorProfile).order_by(MirrorProfile.name)
    if distribution_id is not None:
        q = q.where(MirrorProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_mirror_profile(session: "Session", profile_id: str) -> MirrorProfile:
    p = session.get(MirrorProfile, profile_id)
    if p is None:
        raise KeyError(f"Mirror profile {profile_id!r} not found")
    return p


def update_mirror_profile(
    session: "Session", profile_id: str, **kwargs: object
) -> MirrorProfile:
    p = get_mirror_profile(session, profile_id)
    for key, val in kwargs.items():
        setattr(p, key, val)
    p.updated_at = _now()
    _invalidate(session, profile_id)
    session.flush()
    return p


# ---------------------------------------------------------------------------
# Mirror endpoints
# ---------------------------------------------------------------------------


def add_mirror_endpoint(
    session: "Session",
    profile_id: str,
    url: str,
    priority: int = 0,
    is_default: bool = False,
    requires_auth: bool = False,
    auth_token_id: str | None = None,
) -> MirrorEndpoint:
    get_mirror_profile(session, profile_id)
    existing = session.scalar(
        select(MirrorEndpoint).where(
            MirrorEndpoint.profile_id == profile_id,
            MirrorEndpoint.url == url,
        )
    )
    if existing is not None:
        existing.priority = priority
        existing.is_default = is_default
        existing.requires_auth = requires_auth
        existing.auth_token_id = auth_token_id
        _invalidate(session, profile_id)
        session.flush()
        return existing
    ep = MirrorEndpoint(
        id=_uuid(),
        profile_id=profile_id,
        url=url,
        priority=priority,
        is_default=is_default,
        requires_auth=requires_auth,
        auth_token_id=auth_token_id,
    )
    session.add(ep)
    _invalidate(session, profile_id)
    session.flush()
    return ep


def list_mirror_endpoints(session: "Session", profile_id: str) -> list[MirrorEndpoint]:
    get_mirror_profile(session, profile_id)
    return list(
        session.scalars(
            select(MirrorEndpoint)
            .where(MirrorEndpoint.profile_id == profile_id)
            .order_by(MirrorEndpoint.priority, MirrorEndpoint.url)
        ).all()
    )


# ---------------------------------------------------------------------------
# Cache priority rules
# ---------------------------------------------------------------------------


def add_cache_rule(
    session: "Session",
    profile_id: str,
    source_pattern: str,
    cache_policy: str = "prefer",
    priority: int = 0,
) -> CachePriorityRule:
    if cache_policy not in VALID_CACHE_POLICIES:
        raise ValueError(
            f"Invalid cache_policy {cache_policy!r}. "
            f"Valid: {sorted(VALID_CACHE_POLICIES)}"
        )
    get_mirror_profile(session, profile_id)
    existing = session.scalar(
        select(CachePriorityRule).where(
            CachePriorityRule.profile_id == profile_id,
            CachePriorityRule.source_pattern == source_pattern,
        )
    )
    if existing is not None:
        existing.cache_policy = cache_policy
        existing.priority = priority
        _invalidate(session, profile_id)
        session.flush()
        return existing
    rule = CachePriorityRule(
        id=_uuid(),
        profile_id=profile_id,
        source_pattern=source_pattern,
        cache_policy=cache_policy,
        priority=priority,
    )
    session.add(rule)
    _invalidate(session, profile_id)
    session.flush()
    return rule


def list_cache_rules(
    session: "Session", profile_id: str
) -> list[CachePriorityRule]:
    get_mirror_profile(session, profile_id)
    return list(
        session.scalars(
            select(CachePriorityRule)
            .where(CachePriorityRule.profile_id == profile_id)
            .order_by(CachePriorityRule.priority, CachePriorityRule.source_pattern)
        ).all()
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_mirror_config(session: "Session", profile_id: str) -> MirrorProfile:
    p = get_mirror_profile(session, profile_id)
    endpoints = list_mirror_endpoints(session, profile_id)
    rules = list_cache_rules(session, profile_id)

    config = _render_config(p, endpoints, rules)
    content_hash = "sha256:" + hashlib.sha256(config.encode()).hexdigest()

    p.rendered_mirror_config = config
    p.content_hash = content_hash
    p.rendered_at = datetime.utcnow()
    session.flush()
    return p


def _render_config(
    profile: MirrorProfile,
    endpoints: list[MirrorEndpoint],
    rules: list[CachePriorityRule],
) -> str:
    lines: list[str] = [
        "# OSFabricum Mirror / Cache Configuration",
        f"# profile: {profile.name}",
        "",
        "[mirror]",
        f"offline_mode = {str(profile.offline_mode).lower()}",
        f"cache_ttl_days = {profile.cache_ttl_days}",
    ]
    if profile.max_cache_size_mb is not None:
        lines.append(f"max_cache_size_mb = {profile.max_cache_size_mb}")

    lines.append("")
    lines.append("[endpoints]")
    if endpoints:
        for ep in endpoints:
            default_marker = "  (DEFAULT)" if ep.is_default else ""
            auth_note = "  [auth]" if ep.requires_auth else ""
            lines.append(
                f"  priority={ep.priority:3d}  {ep.url}{default_marker}{auth_note}"
            )
    else:
        lines.append("  # No mirror endpoints defined — using upstream sources directly")

    lines.append("")
    lines.append("[cache_rules]")
    if rules:
        for rule in rules:
            lines.append(
                f"  priority={rule.priority:3d}  {rule.source_pattern:<40s}  {rule.cache_policy}"
            )
    else:
        lines.append("  # No custom cache rules — default policy: prefer")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invalidate(session: "Session", profile_id: str) -> None:
    p = session.get(MirrorProfile, profile_id)
    if p is not None:
        p.content_hash = None
        p.rendered_at = None
