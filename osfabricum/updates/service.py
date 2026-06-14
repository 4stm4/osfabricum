"""M49 — Update / OTA / Recovery Designer service layer."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    RecoveryTarget,
    UpdateChannel,
    UpdateHook,
    UpdateProfile,
    UpdateStrategyKind,
    _now,
    _uuid,
)

VALID_STRATEGIES = frozenset(
    {"full", "a-b", "delta", "recovery", "rollback", "manual"}
)
VALID_VERIFICATION_MODES = frozenset({"strict", "relaxed", "skip"})
VALID_RECOVERY_TARGET_TYPES = frozenset(
    {"minimal", "factory-reset", "emergency-shell", "network-boot", "user-data-wipe"}
)
VALID_HOOK_POINTS = frozenset(
    {
        "pre-download",
        "post-download",
        "pre-apply",
        "post-apply",
        "post-reboot",
        "rollback",
    }
)


# ---------------------------------------------------------------------------
# Strategy kinds
# ---------------------------------------------------------------------------


def list_update_strategy_kinds(session: Session) -> list[UpdateStrategyKind]:
    return list(
        session.scalars(
            sa.select(UpdateStrategyKind).order_by(UpdateStrategyKind.display_order)
        ).all()
    )


# ---------------------------------------------------------------------------
# Update profiles
# ---------------------------------------------------------------------------


def create_update_profile(
    session: Session,
    name: str,
    strategy: str = "full",
    distribution_id: str | None = None,
    description: str = "",
    signing_required: bool = True,
    rollback_enabled: bool = True,
    rollback_window_days: int = 30,
    max_delta_size_mb: int | None = None,
    verification_mode: str = "strict",
) -> UpdateProfile:
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(VALID_STRATEGIES)}")
    if verification_mode not in VALID_VERIFICATION_MODES:
        raise ValueError(
            f"verification_mode must be one of {sorted(VALID_VERIFICATION_MODES)}"
        )
    existing = session.scalars(
        sa.select(UpdateProfile).where(
            UpdateProfile.distribution_id == distribution_id,
            UpdateProfile.name == name,
        )
    ).first()
    if existing:
        raise ValueError(
            f"Update profile '{name}' already exists for distribution {distribution_id!r}"
        )
    now = _now()
    profile = UpdateProfile(
        id=_uuid(),
        name=name,
        distribution_id=distribution_id,
        description=description,
        strategy=strategy,
        signing_required=signing_required,
        rollback_enabled=rollback_enabled,
        rollback_window_days=rollback_window_days,
        max_delta_size_mb=max_delta_size_mb,
        verification_mode=verification_mode,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    return profile


def list_update_profiles(
    session: Session, distribution_id: str | None = None
) -> list[UpdateProfile]:
    q = sa.select(UpdateProfile).order_by(UpdateProfile.name)
    if distribution_id is not None:
        q = q.where(UpdateProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_update_profile(session: Session, profile_id: str) -> UpdateProfile:
    profile = session.get(UpdateProfile, profile_id)
    if profile is None:
        raise KeyError(f"Update profile {profile_id!r} not found")
    return profile


def update_update_profile(
    session: Session, profile_id: str, **kwargs: Any
) -> UpdateProfile:
    profile = get_update_profile(session, profile_id)
    allowed = {
        "name",
        "description",
        "strategy",
        "signing_required",
        "rollback_enabled",
        "rollback_window_days",
        "max_delta_size_mb",
        "verification_mode",
    }
    for k, v in kwargs.items():
        if k not in allowed:
            raise ValueError(f"Unknown field: {k!r}")
        if k == "strategy" and v not in VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(VALID_STRATEGIES)}")
        if k == "verification_mode" and v not in VALID_VERIFICATION_MODES:
            raise ValueError(
                f"verification_mode must be one of {sorted(VALID_VERIFICATION_MODES)}"
            )
        setattr(profile, k, v)
    profile.updated_at = _now()
    _invalidate(session, profile_id)
    session.flush()
    return profile


# ---------------------------------------------------------------------------
# Update channels
# ---------------------------------------------------------------------------


def add_update_channel(
    session: Session,
    profile_id: str,
    name: str,
    priority: int = 0,
    url: str | None = None,
    signing_key_id: str | None = None,
    is_default: bool = False,
) -> UpdateChannel:
    get_update_profile(session, profile_id)
    existing = session.scalars(
        sa.select(UpdateChannel).where(
            UpdateChannel.profile_id == profile_id,
            UpdateChannel.name == name,
        )
    ).first()
    if existing:
        existing.priority = priority
        existing.url = url
        existing.signing_key_id = signing_key_id
        existing.is_default = is_default
        channel = existing
    else:
        channel = UpdateChannel(
            id=_uuid(),
            profile_id=profile_id,
            name=name,
            url=url,
            signing_key_id=signing_key_id,
            priority=priority,
            is_default=is_default,
        )
        session.add(channel)
    _invalidate(session, profile_id)
    session.flush()
    return channel


def list_update_channels(session: Session, profile_id: str) -> list[UpdateChannel]:
    get_update_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(UpdateChannel)
            .where(UpdateChannel.profile_id == profile_id)
            .order_by(UpdateChannel.priority, UpdateChannel.name)
        ).all()
    )


# ---------------------------------------------------------------------------
# Recovery targets
# ---------------------------------------------------------------------------


def add_recovery_target(
    session: Session,
    profile_id: str,
    name: str,
    target_type: str = "minimal",
    kernel_args: str | None = None,
    initramfs_hint: str | None = None,
    is_default: bool = False,
    priority: int = 0,
) -> RecoveryTarget:
    if target_type not in VALID_RECOVERY_TARGET_TYPES:
        raise ValueError(
            f"target_type must be one of {sorted(VALID_RECOVERY_TARGET_TYPES)}"
        )
    get_update_profile(session, profile_id)
    existing = session.scalars(
        sa.select(RecoveryTarget).where(
            RecoveryTarget.profile_id == profile_id,
            RecoveryTarget.name == name,
        )
    ).first()
    if existing:
        existing.target_type = target_type
        existing.kernel_args = kernel_args
        existing.initramfs_hint = initramfs_hint
        existing.is_default = is_default
        existing.priority = priority
        target = existing
    else:
        target = RecoveryTarget(
            id=_uuid(),
            profile_id=profile_id,
            name=name,
            target_type=target_type,
            kernel_args=kernel_args,
            initramfs_hint=initramfs_hint,
            is_default=is_default,
            priority=priority,
        )
        session.add(target)
    _invalidate(session, profile_id)
    session.flush()
    return target


def list_recovery_targets(session: Session, profile_id: str) -> list[RecoveryTarget]:
    get_update_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(RecoveryTarget)
            .where(RecoveryTarget.profile_id == profile_id)
            .order_by(RecoveryTarget.priority, RecoveryTarget.name)
        ).all()
    )


# ---------------------------------------------------------------------------
# Update hooks
# ---------------------------------------------------------------------------


def add_update_hook(
    session: Session,
    profile_id: str,
    hook_point: str,
    script_content: str,
    priority: int = 0,
    is_enabled: bool = True,
) -> UpdateHook:
    if hook_point not in VALID_HOOK_POINTS:
        raise ValueError(f"hook_point must be one of {sorted(VALID_HOOK_POINTS)}")
    get_update_profile(session, profile_id)
    existing = session.scalars(
        sa.select(UpdateHook).where(
            UpdateHook.profile_id == profile_id,
            UpdateHook.hook_point == hook_point,
            UpdateHook.priority == priority,
        )
    ).first()
    if existing:
        existing.script_content = script_content
        existing.is_enabled = is_enabled
        hook = existing
    else:
        hook = UpdateHook(
            id=_uuid(),
            profile_id=profile_id,
            hook_point=hook_point,
            script_content=script_content,
            is_enabled=is_enabled,
            priority=priority,
        )
        session.add(hook)
    _invalidate(session, profile_id)
    session.flush()
    return hook


def list_update_hooks(session: Session, profile_id: str) -> list[UpdateHook]:
    get_update_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(UpdateHook)
            .where(UpdateHook.profile_id == profile_id)
            .order_by(UpdateHook.hook_point, UpdateHook.priority)
        ).all()
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_update_config(session: Session, profile_id: str) -> UpdateProfile:
    profile = get_update_profile(session, profile_id)
    channels = list_update_channels(session, profile_id)
    targets = list_recovery_targets(session, profile_id)
    hooks = list_update_hooks(session, profile_id)

    update_text = _render_update_section(profile, channels, hooks)
    recovery_text = _render_recovery_section(profile, targets)

    combined = "\n".join([update_text, recovery_text])
    digest = hashlib.sha256(combined.encode()).hexdigest()
    content_hash = f"sha256:{digest}"

    profile.rendered_update_config = update_text
    profile.rendered_recovery_config = recovery_text
    profile.content_hash = content_hash
    profile.rendered_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    session.flush()
    return profile


def _render_update_section(
    profile: UpdateProfile,
    channels: list[UpdateChannel],
    hooks: list[UpdateHook],
) -> str:
    lines: list[str] = [
        "## Update Configuration",
        f"# profile: {profile.name}",
        "",
        "[strategy]",
        f"type = {profile.strategy}",
        f"signing_required = {str(profile.signing_required).lower()}",
        f"verification_mode = {profile.verification_mode}",
        f"rollback_enabled = {str(profile.rollback_enabled).lower()}",
        f"rollback_window_days = {profile.rollback_window_days}",
    ]
    if profile.max_delta_size_mb is not None:
        lines.append(f"max_delta_size_mb = {profile.max_delta_size_mb}")
    lines.append("")

    if channels:
        lines.append("[channels]")
        for ch in sorted(channels, key=lambda c: (c.priority, c.name)):
            default_marker = " (default)" if ch.is_default else ""
            lines.append(f"  {ch.name}{default_marker}  priority={ch.priority}")
            if ch.url:
                lines.append(f"    url = {ch.url}")
            if ch.signing_key_id:
                lines.append(f"    signing_key = {ch.signing_key_id}")
        lines.append("")

    _hook_order = [
        "pre-download", "post-download",
        "pre-apply", "post-apply",
        "post-reboot", "rollback",
    ]
    active_hooks = [h for h in hooks if h.is_enabled]
    if active_hooks:
        by_point: dict[str, list[UpdateHook]] = {}
        for h in active_hooks:
            by_point.setdefault(h.hook_point, []).append(h)
        lines.append("[hooks]")
        for point in _hook_order:
            if point not in by_point:
                continue
            for h in sorted(by_point[point], key=lambda x: x.priority):
                lines.append(f"  [{point}]  priority={h.priority}")
                for ln in h.script_content.splitlines():
                    lines.append(f"    {ln}")
        lines.append("")

    return "\n".join(lines)


def _render_recovery_section(
    profile: UpdateProfile, targets: list[RecoveryTarget]
) -> str:
    lines: list[str] = [
        "## Recovery Configuration",
        "",
        "[recovery]",
        f"rollback_enabled = {str(profile.rollback_enabled).lower()}",
        "",
    ]
    if not targets:
        lines.append("# No recovery targets defined.")
        return "\n".join(lines)

    sorted_targets = sorted(targets, key=lambda t: (t.priority, t.name))
    for t in sorted_targets:
        default_marker = " (DEFAULT)" if t.is_default else ""
        lines.append(f"  [{t.name}]{default_marker}  type={t.target_type}")
        if t.kernel_args:
            lines.append(f"    kernel_args = {t.kernel_args}")
        if t.initramfs_hint:
            lines.append(f"    initramfs = {t.initramfs_hint}")
        lines.append(f"    priority = {t.priority}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _invalidate(session: Session, profile_id: str) -> None:
    session.execute(
        sa.update(UpdateProfile)
        .where(UpdateProfile.id == profile_id)
        .values(content_hash=None, rendered_at=None, updated_at=_now())
    )
