"""Business logic for M54 — OS Composition Layers designer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import LayerEntry, LayerKind, LayerProfile, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_LAYER_KINDS: frozenset[str] = frozenset(
    {"base", "bsp", "extension", "app", "compliance", "debug"}
)


def list_layer_kinds(session: "Session") -> list[LayerKind]:
    return list(
        session.scalars(select(LayerKind).order_by(LayerKind.display_order)).all()
    )


def create_layer_profile(
    session: "Session",
    name: str,
    distribution_id: str | None = None,
    description: str = "",
    base_layer: str = "base",
) -> LayerProfile:
    existing = session.scalar(
        select(LayerProfile).where(
            LayerProfile.distribution_id == distribution_id,
            LayerProfile.name == name,
        )
    )
    if existing is not None:
        raise ValueError(
            f"Layer profile {name!r} already exists for distribution {distribution_id!r}"
        )
    now = _now()
    p = LayerProfile(
        id=_uuid(), name=name, distribution_id=distribution_id,
        description=description, base_layer=base_layer,
        created_at=now, updated_at=now,
    )
    session.add(p)
    session.flush()
    return p


def list_layer_profiles(
    session: "Session", distribution_id: str | None = None
) -> list[LayerProfile]:
    q = select(LayerProfile).order_by(LayerProfile.name)
    if distribution_id is not None:
        q = q.where(LayerProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_layer_profile(session: "Session", profile_id: str) -> LayerProfile:
    p = session.get(LayerProfile, profile_id)
    if p is None:
        raise KeyError(f"Layer profile {profile_id!r} not found")
    return p


def update_layer_profile(
    session: "Session", profile_id: str, **kwargs: object
) -> LayerProfile:
    p = get_layer_profile(session, profile_id)
    for k, v in kwargs.items():
        setattr(p, k, v)
    p.updated_at = _now()
    _invalidate(session, profile_id)
    session.flush()
    return p


def add_layer_entry(
    session: "Session",
    profile_id: str,
    name: str,
    layer_kind: str = "extension",
    source_url: str | None = None,
    sha256_hint: str | None = None,
    priority: int = 0,
    is_enabled: bool = True,
    description: str = "",
) -> LayerEntry:
    if layer_kind not in VALID_LAYER_KINDS:
        raise ValueError(
            f"Invalid layer_kind {layer_kind!r}. Valid: {sorted(VALID_LAYER_KINDS)}"
        )
    get_layer_profile(session, profile_id)
    existing = session.scalar(
        select(LayerEntry).where(
            LayerEntry.profile_id == profile_id, LayerEntry.name == name
        )
    )
    if existing is not None:
        existing.layer_kind = layer_kind
        existing.source_url = source_url
        existing.sha256_hint = sha256_hint
        existing.priority = priority
        existing.is_enabled = is_enabled
        existing.description = description
        _invalidate(session, profile_id)
        session.flush()
        return existing
    entry = LayerEntry(
        id=_uuid(), profile_id=profile_id, name=name, layer_kind=layer_kind,
        source_url=source_url, sha256_hint=sha256_hint,
        priority=priority, is_enabled=is_enabled, description=description,
    )
    session.add(entry)
    _invalidate(session, profile_id)
    session.flush()
    return entry


def list_layer_entries(session: "Session", profile_id: str) -> list[LayerEntry]:
    get_layer_profile(session, profile_id)
    return list(
        session.scalars(
            select(LayerEntry)
            .where(LayerEntry.profile_id == profile_id)
            .order_by(LayerEntry.priority, LayerEntry.name)
        ).all()
    )


def render_layer_manifest(session: "Session", profile_id: str) -> LayerProfile:
    p = get_layer_profile(session, profile_id)
    entries = list_layer_entries(session, profile_id)
    manifest = _render_manifest(p, entries)
    content_hash = "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()
    p.rendered_manifest = manifest
    p.content_hash = content_hash
    p.rendered_at = datetime.utcnow()
    session.flush()
    return p


def _render_manifest(profile: LayerProfile, entries: list[LayerEntry]) -> str:
    lines = [
        f"# OSFabricum Layer Manifest — {profile.name}",
        f"# base_layer: {profile.base_layer}",
        "",
        "[manifest]",
        f"profile = {profile.name}",
        f"base_layer = {profile.base_layer}",
        "",
    ]
    enabled = [e for e in entries if e.is_enabled]
    disabled = [e for e in entries if not e.is_enabled]
    lines.append(f"[layers]  # {len(enabled)} enabled, {len(disabled)} disabled")
    if enabled:
        for e in enabled:
            url_part = f"  url={e.source_url}" if e.source_url else ""
            hash_part = f"  sha256={e.sha256_hint}" if e.sha256_hint else ""
            lines.append(
                f"  priority={e.priority:3d}  [{e.layer_kind:12s}]  {e.name}{url_part}{hash_part}"
            )
    else:
        lines.append("  # No enabled layers")
    if disabled:
        lines.append("")
        lines.append("[disabled_layers]")
        for e in disabled:
            lines.append(f"  [{e.layer_kind}]  {e.name}  (disabled)")
    return "\n".join(lines) + "\n"


def _invalidate(session: "Session", profile_id: str) -> None:
    p = session.get(LayerProfile, profile_id)
    if p is not None:
        p.content_hash = None
        p.rendered_at = None
