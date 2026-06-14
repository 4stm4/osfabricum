"""Security / Hardening Designer service (M47).

A ``SecurityProfile`` captures the full hardening configuration for a
distribution image: kernel sysctl parameters, MAC policy rules
(AppArmor/SELinux/TOMOYO/SMACK/Landlock), PAM service config, and
Linux capability grants/drops.

Key functions:

* :func:`create_security_profile` — create a new security profile.
* :func:`get_security_profile` — full detail (sysctl, MAC rules, PAM, caps).
* :func:`update_security_profile` — change name / mac_policy; clears cache.
* :func:`set_sysctl` — upsert a kernel parameter.
* :func:`add_mac_rule` — add a MAC policy rule.
* :func:`add_pam_rule` — add a PAM service configuration entry.
* :func:`set_capability_grant` — upsert capability grants/drops for an executable.
* :func:`render_security_config` — generate sysctl conf, MAC rules, PAM config,
  capability manifest; compute sha256: content hash.
* :func:`list_mac_kinds` — enumerate the seeded MAC framework lookup.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    CapabilityGrant,
    MacRule,
    PamRule,
    SecurityMacKind,
    SecurityProfile,
    SysctlSetting,
)
from osfabricum.db.seed_data import SECURITY_MAC_KINDS
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_MAC_KINDS: frozenset[str] = frozenset(name for name, *_ in SECURITY_MAC_KINDS)
VALID_MODULE_TYPES: frozenset[str] = frozenset(
    {"auth", "account", "session", "password"}
)
VALID_CONTROL_FLAGS: frozenset[str] = frozenset(
    {"required", "requisite", "sufficient", "optional", "include", "substack"}
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: SecurityProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "mac_policy": p.mac_policy,
        "description": p.description,
        "rendered_sysctl": p.rendered_sysctl,
        "rendered_mac_rules": p.rendered_mac_rules,
        "rendered_pam_config": p.rendered_pam_config,
        "rendered_capabilities": p.rendered_capabilities,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _clear_cache(p: SecurityProfile) -> None:
    p.rendered_sysctl = None
    p.rendered_mac_rules = None
    p.rendered_pam_config = None
    p.rendered_capabilities = None
    p.content_hash = None
    p.rendered_at = None


# ---------------------------------------------------------------------------
# MAC kinds (seeded, read-only)
# ---------------------------------------------------------------------------


def list_mac_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": k.name,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in s.scalars(
                select(SecurityMacKind).order_by(SecurityMacKind.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_security_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    mac_policy: str = "none",
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    if mac_policy not in VALID_MAC_KINDS:
        raise ValueError(
            f"unknown MAC policy {mac_policy!r}; "
            f"valid: {', '.join(sorted(VALID_MAC_KINDS))}"
        )
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(SecurityProfile).where(
                SecurityProfile.distribution_id == distribution_id,
                SecurityProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"security profile already exists: {name!r}")
        p = SecurityProfile(
            name=name,
            distribution_id=distribution_id,
            mac_policy=mac_policy,
            description=description,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def list_security_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(SecurityProfile).order_by(SecurityProfile.name)
        if distribution_id is not None:
            q = q.where(SecurityProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_security_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile with sysctl settings, MAC rules, PAM rules, capability grants."""
    with sync_session(db_url) as s:
        p = s.get(SecurityProfile, profile_id)
        if p is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["sysctl"] = [
            {
                "id": sc.id,
                "key": sc.key,
                "value": sc.value,
                "description": sc.description,
            }
            for sc in s.scalars(
                select(SysctlSetting)
                .where(SysctlSetting.profile_id == profile_id)
                .order_by(SysctlSetting.key)
            ).all()
        ]

        result["mac_rules"] = [
            {
                "id": mr.id,
                "subject": mr.subject,
                "rule_text": mr.rule_text,
                "is_enforcing": mr.is_enforcing,
                "priority": mr.priority,
                "comment": mr.comment,
            }
            for mr in s.scalars(
                select(MacRule)
                .where(MacRule.profile_id == profile_id)
                .order_by(MacRule.priority, MacRule.subject)
            ).all()
        ]

        result["pam_rules"] = [
            {
                "id": pr.id,
                "service": pr.service,
                "module_type": pr.module_type,
                "control_flag": pr.control_flag,
                "module_path": pr.module_path,
                "module_args": pr.module_args,
                "priority": pr.priority,
            }
            for pr in s.scalars(
                select(PamRule)
                .where(PamRule.profile_id == profile_id)
                .order_by(PamRule.service, PamRule.module_type, PamRule.priority)
            ).all()
        ]

        result["capabilities"] = [
            {
                "id": cg.id,
                "executable": cg.executable,
                "add_caps": cg.add_caps,
                "drop_caps": cg.drop_caps,
                "no_new_privs": cg.no_new_privs,
                "description": cg.description,
            }
            for cg in s.scalars(
                select(CapabilityGrant)
                .where(CapabilityGrant.profile_id == profile_id)
                .order_by(CapabilityGrant.executable)
            ).all()
        ]

        return result


def update_security_profile(
    profile_id: str,
    *,
    name: str | None = None,
    mac_policy: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update profile fields; clears rendered cache."""
    if mac_policy is not None and mac_policy not in VALID_MAC_KINDS:
        raise ValueError(
            f"unknown MAC policy {mac_policy!r}; "
            f"valid: {', '.join(sorted(VALID_MAC_KINDS))}"
        )
    with sync_session(db_url) as s:
        p = s.get(SecurityProfile, profile_id)
        if p is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        if name is not None:
            p.name = name
        if mac_policy is not None:
            p.mac_policy = mac_policy
        if description is not None:
            p.description = description
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


# ---------------------------------------------------------------------------
# Sysctl settings (upsert)
# ---------------------------------------------------------------------------


def set_sysctl(
    profile_id: str,
    key: str,
    value: str,
    *,
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Upsert a kernel sysctl parameter in a security profile."""
    with sync_session(db_url) as s:
        p = s.get(SecurityProfile, profile_id)
        if p is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        existing = s.scalars(
            select(SysctlSetting).where(
                SysctlSetting.profile_id == profile_id,
                SysctlSetting.key == key,
            )
        ).first()
        if existing is not None:
            existing.value = value
            existing.description = description
            sc = existing
        else:
            sc = SysctlSetting(
                profile_id=profile_id,
                key=key,
                value=value,
                description=description,
            )
            s.add(sc)
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return {
            "id": sc.id,
            "profile_id": profile_id,
            "key": key,
            "value": value,
            "description": description,
        }


# ---------------------------------------------------------------------------
# MAC rules
# ---------------------------------------------------------------------------


def add_mac_rule(
    profile_id: str,
    subject: str,
    rule_text: str,
    *,
    is_enforcing: bool = True,
    priority: int = 100,
    comment: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a MAC policy rule to a security profile."""
    with sync_session(db_url) as s:
        if s.get(SecurityProfile, profile_id) is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        mr = MacRule(
            profile_id=profile_id,
            subject=subject,
            rule_text=rule_text,
            is_enforcing=is_enforcing,
            priority=priority,
            comment=comment,
        )
        s.add(mr)
        s.commit()
        return {
            "id": mr.id,
            "profile_id": profile_id,
            "subject": subject,
            "rule_text": rule_text,
            "is_enforcing": is_enforcing,
            "priority": priority,
            "comment": comment,
        }


# ---------------------------------------------------------------------------
# PAM rules
# ---------------------------------------------------------------------------


def add_pam_rule(
    profile_id: str,
    service: str,
    module_type: str,
    control_flag: str,
    module_path: str,
    *,
    module_args: str | None = None,
    priority: int = 100,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a PAM service configuration entry to a security profile."""
    if module_type not in VALID_MODULE_TYPES:
        raise ValueError(
            f"unknown module type {module_type!r}; "
            f"valid: {', '.join(sorted(VALID_MODULE_TYPES))}"
        )
    if control_flag not in VALID_CONTROL_FLAGS:
        raise ValueError(
            f"unknown control flag {control_flag!r}; "
            f"valid: {', '.join(sorted(VALID_CONTROL_FLAGS))}"
        )
    with sync_session(db_url) as s:
        if s.get(SecurityProfile, profile_id) is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        existing = s.scalars(
            select(PamRule).where(
                PamRule.profile_id == profile_id,
                PamRule.service == service,
                PamRule.module_type == module_type,
                PamRule.module_path == module_path,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"PAM rule for {service!r}/{module_type}/{module_path} already exists"
            )
        pr = PamRule(
            profile_id=profile_id,
            service=service,
            module_type=module_type,
            control_flag=control_flag,
            module_path=module_path,
            module_args=module_args,
            priority=priority,
        )
        s.add(pr)
        s.commit()
        return {
            "id": pr.id,
            "profile_id": profile_id,
            "service": service,
            "module_type": module_type,
            "control_flag": control_flag,
            "module_path": module_path,
            "module_args": module_args,
            "priority": priority,
        }


# ---------------------------------------------------------------------------
# Capability grants (upsert)
# ---------------------------------------------------------------------------


def set_capability_grant(
    profile_id: str,
    executable: str,
    *,
    add_caps: str | None = None,
    drop_caps: str | None = None,
    no_new_privs: bool = False,
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Upsert capability grants/drops for an executable in a security profile."""
    with sync_session(db_url) as s:
        p = s.get(SecurityProfile, profile_id)
        if p is None:
            raise ValueError(f"security profile not found: {profile_id!r}")
        existing = s.scalars(
            select(CapabilityGrant).where(
                CapabilityGrant.profile_id == profile_id,
                CapabilityGrant.executable == executable,
            )
        ).first()
        if existing is not None:
            existing.add_caps = add_caps
            existing.drop_caps = drop_caps
            existing.no_new_privs = no_new_privs
            existing.description = description
            cg = existing
        else:
            cg = CapabilityGrant(
                profile_id=profile_id,
                executable=executable,
                add_caps=add_caps,
                drop_caps=drop_caps,
                no_new_privs=no_new_privs,
                description=description,
            )
            s.add(cg)
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return {
            "id": cg.id,
            "profile_id": profile_id,
            "executable": executable,
            "add_caps": add_caps,
            "drop_caps": drop_caps,
            "no_new_privs": no_new_privs,
            "description": description,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_SYSCTL_HEADER = (
    "# /etc/sysctl.d/99-osfabricum.conf — generated by OSFabricum M47\n"
    "# Kernel security hardening parameters\n"
)
_MAC_HEADER = "# MAC policy rules — generated by OSFabricum M47\n"
_PAM_HEADER = "# PAM configuration — generated by OSFabricum M47\n"
_CAPS_HEADER = "# Capability grants — generated by OSFabricum M47\n"


def _build_sysctl(settings: list[SysctlSetting]) -> str:
    if not settings:
        return _SYSCTL_HEADER + "# no sysctl settings configured\n"
    sorted_settings = sorted(settings, key=lambda sc: sc.key)
    lines: list[str] = [_SYSCTL_HEADER]
    for sc in sorted_settings:
        if sc.description:
            lines.append(f"# {sc.description}\n")
        lines.append(f"{sc.key} = {sc.value}\n")
    return "".join(lines)


def _build_mac_rules(mac_rules: list[MacRule], mac_policy: str) -> str:
    if not mac_rules:
        return (
            _MAC_HEADER
            + f"# MAC policy: {mac_policy}\n"
            + "# no MAC rules configured\n"
        )
    sorted_rules = sorted(mac_rules, key=lambda mr: (mr.priority, mr.subject))
    lines: list[str] = [_MAC_HEADER, f"# MAC policy: {mac_policy}\n\n"]
    current_subject = None
    for mr in sorted_rules:
        if mr.subject != current_subject:
            current_subject = mr.subject
            mode = "enforce" if mr.is_enforcing else "permissive"
            lines.append(f"##-- {mr.subject} ({mode}) --##\n")
            if mr.comment:
                lines.append(f"# {mr.comment}\n")
        lines.append(mr.rule_text)
        if not mr.rule_text.endswith("\n"):
            lines.append("\n")
        lines.append("\n")
    return "".join(lines)


def _build_pam_config(pam_rules: list[PamRule]) -> str:
    if not pam_rules:
        return _PAM_HEADER + "# no PAM rules configured\n"
    # Group by service
    from collections import defaultdict  # noqa: PLC0415

    by_service: dict[str, list[PamRule]] = defaultdict(list)
    for pr in pam_rules:
        by_service[pr.service].append(pr)

    lines: list[str] = [_PAM_HEADER]
    for service in sorted(by_service):
        lines.append(f"\n##-- /etc/pam.d/{service} --##\n")
        # Sort by module_type canonical order, then priority
        type_order = {"auth": 0, "account": 1, "session": 2, "password": 3}
        sorted_rules = sorted(
            by_service[service],
            key=lambda pr: (type_order.get(pr.module_type, 9), pr.priority),
        )
        for pr in sorted_rules:
            args = f" {pr.module_args}" if pr.module_args else ""
            lines.append(
                f"{pr.module_type:<12}{pr.control_flag:<16}{pr.module_path}{args}\n"
            )
    return "".join(lines)


def _build_capabilities(capability_grants: list[CapabilityGrant]) -> str:
    if not capability_grants:
        return _CAPS_HEADER + "# no capability grants configured\n"
    sorted_caps = sorted(capability_grants, key=lambda cg: cg.executable)
    lines: list[str] = [_CAPS_HEADER]
    for cg in sorted_caps:
        if cg.description:
            lines.append(f"# {cg.description}\n")
        parts: list[str] = [cg.executable]
        if cg.add_caps:
            parts.append(f"add={cg.add_caps}")
        if cg.drop_caps:
            parts.append(f"drop={cg.drop_caps}")
        if cg.no_new_privs:
            parts.append("no_new_privs=yes")
        lines.append("  ".join(parts) + "\n")
    return "".join(lines)


def render_security_config(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate sysctl conf, MAC rules, PAM config, capability manifest; store on row.

    All outputs are concatenated for the deterministic sha256: hash.
    """
    with sync_session(db_url) as s:
        p = s.get(SecurityProfile, profile_id)
        if p is None:
            raise ValueError(f"security profile not found: {profile_id!r}")

        sysctl_settings = s.scalars(
            select(SysctlSetting).where(SysctlSetting.profile_id == profile_id)
        ).all()
        mac_rules = s.scalars(
            select(MacRule).where(MacRule.profile_id == profile_id)
        ).all()
        pam_rules = s.scalars(
            select(PamRule).where(PamRule.profile_id == profile_id)
        ).all()
        capability_grants = s.scalars(
            select(CapabilityGrant).where(CapabilityGrant.profile_id == profile_id)
        ).all()

        rendered_sysctl = _build_sysctl(list(sysctl_settings))
        rendered_mac = _build_mac_rules(list(mac_rules), p.mac_policy)
        rendered_pam = _build_pam_config(list(pam_rules))
        rendered_caps = _build_capabilities(list(capability_grants))

        body = (
            rendered_sysctl
            + "\n---\n"
            + rendered_mac
            + "\n---\n"
            + rendered_pam
            + "\n---\n"
            + rendered_caps
        )
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_sysctl = rendered_sysctl
        p.rendered_mac_rules = rendered_mac
        p.rendered_pam_config = rendered_pam
        p.rendered_capabilities = rendered_caps
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_sysctl": rendered_sysctl,
            "rendered_mac_rules": rendered_mac,
            "rendered_pam_config": rendered_pam,
            "rendered_capabilities": rendered_caps,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "sysctl_count": len(sysctl_settings),
            "mac_rule_count": len(mac_rules),
            "pam_rule_count": len(pam_rules),
            "capability_count": len(capability_grants),
        }
