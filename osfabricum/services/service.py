"""Service / Init / Device Manager Designer service (M46).

A ``ServiceProfile`` captures the full service topology for a distribution
image: systemd unit files, udev device rules, and drop-in overrides for
existing system units.

Key functions:

* :func:`create_service_profile` — create a new service profile.
* :func:`get_service_profile` — full detail (entries, device rules, overrides).
* :func:`update_service_profile` — change name / init_system; clears cache.
* :func:`add_service_entry` — declare a systemd/init service unit.
* :func:`add_device_rule` — add a udev rule.
* :func:`set_unit_override` — upsert a drop-in override fragment.
* :func:`render_service_config` — generate unit files, udev rules, override
  manifests; compute sha256: content hash.
* :func:`list_init_system_kinds` — enumerate the seeded init system lookup.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    DeviceRule,
    InitSystemKind,
    ServiceEntry,
    ServiceProfile,
    SystemdUnitOverride,
)
from osfabricum.db.seed_data import INIT_SYSTEM_KINDS
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_INIT_SYSTEMS: frozenset[str] = frozenset(name for name, *_ in INIT_SYSTEM_KINDS)
VALID_UNIT_TYPES: frozenset[str] = frozenset(
    {"service", "socket", "timer", "target", "path"}
)
VALID_RESTART_POLICIES: frozenset[str] = frozenset(
    {"no", "on-failure", "always", "on-abnormal", "on-watchdog", "on-abort"}
)
VALID_UDEV_ACTIONS: frozenset[str] = frozenset(
    {"add", "remove", "change", "bind", "unbind", "any"}
)
VALID_OVERRIDE_SECTIONS: frozenset[str] = frozenset(
    {"Unit", "Service", "Socket", "Timer", "Install", "Mount", "Automount"}
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: ServiceProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "init_system": p.init_system,
        "description": p.description,
        "rendered_units": p.rendered_units,
        "rendered_udev": p.rendered_udev,
        "rendered_overrides": p.rendered_overrides,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _clear_cache(p: ServiceProfile) -> None:
    p.rendered_units = None
    p.rendered_udev = None
    p.rendered_overrides = None
    p.content_hash = None
    p.rendered_at = None


# ---------------------------------------------------------------------------
# Init system kinds (seeded, read-only)
# ---------------------------------------------------------------------------


def list_init_system_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": k.name,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in s.scalars(
                select(InitSystemKind).order_by(InitSystemKind.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_service_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    init_system: str = "systemd",
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    if init_system not in VALID_INIT_SYSTEMS:
        raise ValueError(
            f"unknown init system {init_system!r}; "
            f"valid: {', '.join(sorted(VALID_INIT_SYSTEMS))}"
        )
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(ServiceProfile).where(
                ServiceProfile.distribution_id == distribution_id,
                ServiceProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"service profile already exists: {name!r}")
        p = ServiceProfile(
            name=name,
            distribution_id=distribution_id,
            init_system=init_system,
            description=description,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def list_service_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(ServiceProfile).order_by(ServiceProfile.name)
        if distribution_id is not None:
            q = q.where(ServiceProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_service_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile with service entries, device rules, and unit overrides."""
    with sync_session(db_url) as s:
        p = s.get(ServiceProfile, profile_id)
        if p is None:
            raise ValueError(f"service profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["entries"] = [
            {
                "id": e.id,
                "name": e.name,
                "unit_type": e.unit_type,
                "description": e.description,
                "exec_start": e.exec_start,
                "exec_stop": e.exec_stop,
                "exec_pre_start": e.exec_pre_start,
                "restart_policy": e.restart_policy,
                "wanted_by": e.wanted_by,
                "after": e.after,
                "requires": e.requires,
                "environment": e.environment,
                "working_directory": e.working_directory,
                "run_user": e.run_user,
                "run_group": e.run_group,
                "is_enabled": e.is_enabled,
                "is_masked": e.is_masked,
                "priority": e.priority,
            }
            for e in s.scalars(
                select(ServiceEntry)
                .where(ServiceEntry.profile_id == profile_id)
                .order_by(ServiceEntry.priority, ServiceEntry.name)
            ).all()
        ]

        result["device_rules"] = [
            {
                "id": dr.id,
                "subsystem": dr.subsystem,
                "kernel_pattern": dr.kernel_pattern,
                "attr_filter": dr.attr_filter,
                "udev_action": dr.udev_action,
                "symlink": dr.symlink,
                "mode": dr.mode,
                "owner": dr.owner,
                "group_name": dr.group_name,
                "run_command": dr.run_command,
                "priority": dr.priority,
                "comment": dr.comment,
            }
            for dr in s.scalars(
                select(DeviceRule)
                .where(DeviceRule.profile_id == profile_id)
                .order_by(DeviceRule.priority, DeviceRule.id)
            ).all()
        ]

        result["unit_overrides"] = [
            {
                "id": uo.id,
                "unit_name": uo.unit_name,
                "section": uo.section,
                "override_content": uo.override_content,
            }
            for uo in s.scalars(
                select(SystemdUnitOverride)
                .where(SystemdUnitOverride.profile_id == profile_id)
                .order_by(SystemdUnitOverride.unit_name)
            ).all()
        ]

        return result


def update_service_profile(
    profile_id: str,
    *,
    name: str | None = None,
    init_system: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update profile fields; clears rendered cache."""
    if init_system is not None and init_system not in VALID_INIT_SYSTEMS:
        raise ValueError(
            f"unknown init system {init_system!r}; "
            f"valid: {', '.join(sorted(VALID_INIT_SYSTEMS))}"
        )
    with sync_session(db_url) as s:
        p = s.get(ServiceProfile, profile_id)
        if p is None:
            raise ValueError(f"service profile not found: {profile_id!r}")
        if name is not None:
            p.name = name
        if init_system is not None:
            p.init_system = init_system
        if description is not None:
            p.description = description
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


# ---------------------------------------------------------------------------
# Service entries
# ---------------------------------------------------------------------------


def add_service_entry(
    profile_id: str,
    name: str,
    *,
    unit_type: str = "service",
    description: str = "",
    exec_start: str | None = None,
    exec_stop: str | None = None,
    exec_pre_start: str | None = None,
    restart_policy: str = "no",
    wanted_by: str = "multi-user.target",
    after: str | None = None,
    requires: str | None = None,
    environment: str | None = None,
    working_directory: str | None = None,
    run_user: str | None = None,
    run_group: str | None = None,
    is_enabled: bool = True,
    is_masked: bool = False,
    priority: int = 100,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a service/socket/timer/target/path unit to a service profile."""
    if unit_type not in VALID_UNIT_TYPES:
        raise ValueError(
            f"unknown unit type {unit_type!r}; "
            f"valid: {', '.join(sorted(VALID_UNIT_TYPES))}"
        )
    if restart_policy not in VALID_RESTART_POLICIES:
        raise ValueError(
            f"unknown restart policy {restart_policy!r}; "
            f"valid: {', '.join(sorted(VALID_RESTART_POLICIES))}"
        )
    with sync_session(db_url) as s:
        if s.get(ServiceProfile, profile_id) is None:
            raise ValueError(f"service profile not found: {profile_id!r}")
        existing = s.scalars(
            select(ServiceEntry).where(
                ServiceEntry.profile_id == profile_id,
                ServiceEntry.name == name,
                ServiceEntry.unit_type == unit_type,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"service entry {name!r} ({unit_type}) already exists in profile"
            )
        e = ServiceEntry(
            profile_id=profile_id,
            name=name,
            unit_type=unit_type,
            description=description,
            exec_start=exec_start,
            exec_stop=exec_stop,
            exec_pre_start=exec_pre_start,
            restart_policy=restart_policy,
            wanted_by=wanted_by,
            after=after,
            requires=requires,
            environment=environment,
            working_directory=working_directory,
            run_user=run_user,
            run_group=run_group,
            is_enabled=is_enabled,
            is_masked=is_masked,
            priority=priority,
        )
        s.add(e)
        s.commit()
        return {
            "id": e.id,
            "profile_id": profile_id,
            "name": name,
            "unit_type": unit_type,
            "description": description,
            "exec_start": exec_start,
            "exec_stop": exec_stop,
            "exec_pre_start": exec_pre_start,
            "restart_policy": restart_policy,
            "wanted_by": wanted_by,
            "after": after,
            "requires": requires,
            "environment": environment,
            "working_directory": working_directory,
            "run_user": run_user,
            "run_group": run_group,
            "is_enabled": is_enabled,
            "is_masked": is_masked,
            "priority": priority,
        }


# ---------------------------------------------------------------------------
# Device rules
# ---------------------------------------------------------------------------


def add_device_rule(
    profile_id: str,
    *,
    subsystem: str | None = None,
    kernel_pattern: str | None = None,
    attr_filter: str | None = None,
    udev_action: str = "add",
    symlink: str | None = None,
    mode: str | None = None,
    owner: str | None = None,
    group_name: str | None = None,
    run_command: str | None = None,
    priority: int = 90,
    comment: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a udev rule to a service profile."""
    if udev_action not in VALID_UDEV_ACTIONS:
        raise ValueError(
            f"unknown udev action {udev_action!r}; "
            f"valid: {', '.join(sorted(VALID_UDEV_ACTIONS))}"
        )
    with sync_session(db_url) as s:
        if s.get(ServiceProfile, profile_id) is None:
            raise ValueError(f"service profile not found: {profile_id!r}")
        dr = DeviceRule(
            profile_id=profile_id,
            subsystem=subsystem,
            kernel_pattern=kernel_pattern,
            attr_filter=attr_filter,
            udev_action=udev_action,
            symlink=symlink,
            mode=mode,
            owner=owner,
            group_name=group_name,
            run_command=run_command,
            priority=priority,
            comment=comment,
        )
        s.add(dr)
        s.commit()
        return {
            "id": dr.id,
            "profile_id": profile_id,
            "subsystem": subsystem,
            "kernel_pattern": kernel_pattern,
            "attr_filter": attr_filter,
            "udev_action": udev_action,
            "symlink": symlink,
            "mode": mode,
            "owner": owner,
            "group_name": group_name,
            "run_command": run_command,
            "priority": priority,
            "comment": comment,
        }


# ---------------------------------------------------------------------------
# Unit overrides (upsert)
# ---------------------------------------------------------------------------


def set_unit_override(
    profile_id: str,
    unit_name: str,
    override_content: str,
    *,
    section: str = "Service",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Upsert a drop-in override fragment for an existing systemd unit."""
    if section not in VALID_OVERRIDE_SECTIONS:
        raise ValueError(
            f"unknown section {section!r}; "
            f"valid: {', '.join(sorted(VALID_OVERRIDE_SECTIONS))}"
        )
    with sync_session(db_url) as s:
        p = s.get(ServiceProfile, profile_id)
        if p is None:
            raise ValueError(f"service profile not found: {profile_id!r}")
        existing = s.scalars(
            select(SystemdUnitOverride).where(
                SystemdUnitOverride.profile_id == profile_id,
                SystemdUnitOverride.unit_name == unit_name,
            )
        ).first()
        if existing is not None:
            existing.section = section
            existing.override_content = override_content
            uo = existing
        else:
            uo = SystemdUnitOverride(
                profile_id=profile_id,
                unit_name=unit_name,
                section=section,
                override_content=override_content,
            )
            s.add(uo)
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return {
            "id": uo.id,
            "profile_id": profile_id,
            "unit_name": unit_name,
            "section": section,
            "override_content": override_content,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_UNIT_HEADER = "# Generated by OSFabricum M46 — do not edit manually\n"
_UDEV_HEADER = "# /etc/udev/rules.d/ — generated by OSFabricum M46\n"
_OVERRIDE_HEADER = "# systemd drop-in overrides — generated by OSFabricum M46\n"


def _build_unit_file(entry: ServiceEntry) -> str:
    """Generate a systemd unit file (.service/.socket/.timer/etc.)."""
    lines = [_UNIT_HEADER, "[Unit]\n"]
    if entry.description:
        lines.append(f"Description={entry.description}\n")
    if entry.after:
        lines.append(f"After={entry.after}\n")
    if entry.requires:
        lines.append(f"Requires={entry.requires}\n")

    if entry.unit_type == "service":
        lines.append("\n[Service]\n")
        lines.append("Type=simple\n")
        if entry.exec_pre_start:
            lines.append(f"ExecStartPre={entry.exec_pre_start}\n")
        if entry.exec_start:
            lines.append(f"ExecStart={entry.exec_start}\n")
        if entry.exec_stop:
            lines.append(f"ExecStop={entry.exec_stop}\n")
        lines.append(f"Restart={entry.restart_policy}\n")
        if entry.working_directory:
            lines.append(f"WorkingDirectory={entry.working_directory}\n")
        if entry.run_user:
            lines.append(f"User={entry.run_user}\n")
        if entry.run_group:
            lines.append(f"Group={entry.run_group}\n")
        if entry.environment:
            for env_line in entry.environment.splitlines():
                if env_line.strip():
                    lines.append(f"Environment={env_line.strip()}\n")
    elif entry.unit_type == "socket":
        lines.append("\n[Socket]\n")
        if entry.exec_start:
            lines.append(f"ListenStream={entry.exec_start}\n")
    elif entry.unit_type == "timer":
        lines.append("\n[Timer]\n")
        if entry.exec_start:
            lines.append(f"OnCalendar={entry.exec_start}\n")
        lines.append("Persistent=true\n")
    elif entry.unit_type == "target":
        pass  # [Unit] block is sufficient
    elif entry.unit_type == "path":
        lines.append("\n[Path]\n")
        if entry.exec_start:
            lines.append(f"PathExists={entry.exec_start}\n")

    lines.append("\n[Install]\n")
    lines.append(f"WantedBy={entry.wanted_by}\n")

    return "".join(lines)


def _build_units(entries: list[ServiceEntry]) -> str:
    """Build concatenated unit file content sorted by priority then name."""
    sorted_entries = sorted(entries, key=lambda e: (e.priority, e.name))
    sections: list[str] = []
    for entry in sorted_entries:
        suffix = entry.unit_type if entry.unit_type != "service" else "service"
        filename = f"{entry.name}.{suffix}"
        masked_note = "# MASKED\n" if entry.is_masked else ""
        enabled_note = "" if entry.is_enabled else "# DISABLED\n"
        sections.append(
            f"##-- /etc/systemd/system/{filename} --##\n"
            + masked_note
            + enabled_note
            + _build_unit_file(entry)
        )
    if not sections:
        return "# no service entries configured\n"
    return "\n".join(sections)


def _udev_rule_line(dr: DeviceRule) -> str:
    """Generate a single udev rule line."""
    parts: list[str] = []
    if dr.subsystem:
        parts.append(f'SUBSYSTEM=="{dr.subsystem}"')
    if dr.kernel_pattern:
        parts.append(f'KERNEL=="{dr.kernel_pattern}"')
    if dr.attr_filter:
        parts.append(dr.attr_filter.strip())
    if dr.udev_action != "any":
        parts.append(f'ACTION=="{dr.udev_action}"')

    assignments: list[str] = []
    if dr.symlink:
        assignments.append(f'SYMLINK+="{dr.symlink}"')
    if dr.mode:
        assignments.append(f'MODE="{dr.mode}"')
    if dr.owner:
        assignments.append(f'OWNER="{dr.owner}"')
    if dr.group_name:
        assignments.append(f'GROUP="{dr.group_name}"')
    if dr.run_command:
        assignments.append(f'RUN+="{dr.run_command}"')

    rule = ", ".join(parts + assignments)
    if dr.comment:
        rule += f"  # {dr.comment}"
    return rule


def _build_udev(device_rules: list[DeviceRule]) -> str:
    """Build udev rules file content."""
    if not device_rules:
        return _UDEV_HEADER + "# no device rules configured\n"
    sorted_rules = sorted(device_rules, key=lambda dr: (dr.priority, dr.id))
    current_priority = None
    lines: list[str] = [_UDEV_HEADER]
    for dr in sorted_rules:
        if dr.priority != current_priority:
            current_priority = dr.priority
            lines.append(f"\n# priority {dr.priority}\n")
        lines.append(_udev_rule_line(dr) + "\n")
    return "".join(lines)


def _build_overrides(unit_overrides: list[SystemdUnitOverride]) -> str:
    """Build drop-in override manifest."""
    if not unit_overrides:
        return _OVERRIDE_HEADER + "# no unit overrides configured\n"
    sorted_overrides = sorted(unit_overrides, key=lambda uo: uo.unit_name)
    sections: list[str] = [_OVERRIDE_HEADER]
    for uo in sorted_overrides:
        sections.append(
            f"\n##-- /etc/systemd/system/{uo.unit_name}.d/override.conf --##\n"
            f"[{uo.section}]\n"
            + uo.override_content
            + ("\n" if not uo.override_content.endswith("\n") else "")
        )
    return "".join(sections)


def render_service_config(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate unit files, udev rules, override manifests; store on row.

    All outputs are concatenated for the deterministic sha256: hash.
    """
    with sync_session(db_url) as s:
        p = s.get(ServiceProfile, profile_id)
        if p is None:
            raise ValueError(f"service profile not found: {profile_id!r}")

        entries = s.scalars(
            select(ServiceEntry).where(ServiceEntry.profile_id == profile_id)
        ).all()
        device_rules = s.scalars(
            select(DeviceRule).where(DeviceRule.profile_id == profile_id)
        ).all()
        unit_overrides = s.scalars(
            select(SystemdUnitOverride).where(
                SystemdUnitOverride.profile_id == profile_id
            )
        ).all()

        rendered_units = _build_units(list(entries))
        rendered_udev = _build_udev(list(device_rules))
        rendered_overrides = _build_overrides(list(unit_overrides))

        body = (
            rendered_units
            + "\n---\n"
            + rendered_udev
            + "\n---\n"
            + rendered_overrides
        )
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_units = rendered_units
        p.rendered_udev = rendered_udev
        p.rendered_overrides = rendered_overrides
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_units": rendered_units,
            "rendered_udev": rendered_udev,
            "rendered_overrides": rendered_overrides,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "entry_count": len(entries),
            "device_rule_count": len(device_rules),
            "override_count": len(unit_overrides),
        }
