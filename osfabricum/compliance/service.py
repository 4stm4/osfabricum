"""M48 — License / SBOM / Vuln / Source Compliance Designer service layer."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    ComplianceProfile,
    LicenseRule,
    SbomEntry,
    SpdxLicenseKind,
    VulnGate,
)
from osfabricum.db.models import _now, _uuid

VALID_VULN_ACTIONS = frozenset({"block", "warn", "ignore"})
VALID_VULN_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
VALID_LICENSE_POLICIES = frozenset({"allow", "deny", "warn"})
VALID_BLOCK_THRESHOLDS = frozenset({"none", "info", "low", "medium", "high", "critical"})

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "none": 5}


# ---------------------------------------------------------------------------
# SPDX lookup
# ---------------------------------------------------------------------------

def list_spdx_license_kinds(session: Session) -> list[SpdxLicenseKind]:
    return list(
        session.scalars(
            sa.select(SpdxLicenseKind).order_by(SpdxLicenseKind.display_order)
        ).all()
    )


# ---------------------------------------------------------------------------
# Compliance profiles
# ---------------------------------------------------------------------------

def create_compliance_profile(
    session: Session,
    name: str,
    distribution_id: str | None = None,
    description: str = "",
    allow_copyleft: bool = True,
    allow_proprietary: bool = False,
    min_vuln_severity_to_block: str = "critical",
    require_sbom: bool = True,
) -> ComplianceProfile:
    if min_vuln_severity_to_block not in VALID_BLOCK_THRESHOLDS:
        raise ValueError(
            f"min_vuln_severity_to_block must be one of {sorted(VALID_BLOCK_THRESHOLDS)}"
        )
    existing = session.scalars(
        sa.select(ComplianceProfile).where(
            ComplianceProfile.distribution_id == distribution_id,
            ComplianceProfile.name == name,
        )
    ).first()
    if existing:
        raise ValueError(
            f"Compliance profile '{name}' already exists for distribution {distribution_id!r}"
        )
    now = _now()
    profile = ComplianceProfile(
        id=_uuid(),
        name=name,
        distribution_id=distribution_id,
        description=description,
        allow_copyleft=allow_copyleft,
        allow_proprietary=allow_proprietary,
        min_vuln_severity_to_block=min_vuln_severity_to_block,
        require_sbom=require_sbom,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    return profile


def list_compliance_profiles(
    session: Session, distribution_id: str | None = None
) -> list[ComplianceProfile]:
    q = sa.select(ComplianceProfile).order_by(ComplianceProfile.name)
    if distribution_id is not None:
        q = q.where(ComplianceProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_compliance_profile(session: Session, profile_id: str) -> ComplianceProfile:
    profile = session.get(ComplianceProfile, profile_id)
    if profile is None:
        raise KeyError(f"Compliance profile {profile_id!r} not found")
    return profile


def update_compliance_profile(
    session: Session, profile_id: str, **kwargs: Any
) -> ComplianceProfile:
    profile = get_compliance_profile(session, profile_id)
    allowed = {
        "name", "description", "allow_copyleft", "allow_proprietary",
        "min_vuln_severity_to_block", "require_sbom",
    }
    for k, v in kwargs.items():
        if k not in allowed:
            raise ValueError(f"Unknown field: {k!r}")
        if k == "min_vuln_severity_to_block" and v not in VALID_BLOCK_THRESHOLDS:
            raise ValueError(
                f"min_vuln_severity_to_block must be one of {sorted(VALID_BLOCK_THRESHOLDS)}"
            )
        setattr(profile, k, v)
    profile.updated_at = _now()
    profile.content_hash = None
    profile.rendered_at = None
    session.flush()
    return profile


# ---------------------------------------------------------------------------
# License rules
# ---------------------------------------------------------------------------

def set_license_rule(
    session: Session,
    profile_id: str,
    spdx_id: str,
    policy: str,
    reason: str | None = None,
) -> LicenseRule:
    if policy not in VALID_LICENSE_POLICIES:
        raise ValueError(f"policy must be one of {sorted(VALID_LICENSE_POLICIES)}")
    get_compliance_profile(session, profile_id)
    existing = session.scalars(
        sa.select(LicenseRule).where(
            LicenseRule.profile_id == profile_id,
            LicenseRule.spdx_id == spdx_id,
        )
    ).first()
    if existing:
        existing.policy = policy
        existing.reason = reason
        rule = existing
    else:
        rule = LicenseRule(
            id=_uuid(),
            profile_id=profile_id,
            spdx_id=spdx_id,
            policy=policy,
            reason=reason,
        )
        session.add(rule)
    _invalidate(session, profile_id)
    session.flush()
    return rule


def list_license_rules(session: Session, profile_id: str) -> list[LicenseRule]:
    get_compliance_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(LicenseRule)
            .where(LicenseRule.profile_id == profile_id)
            .order_by(LicenseRule.spdx_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# Vuln gates
# ---------------------------------------------------------------------------

def set_vuln_gate(
    session: Session,
    profile_id: str,
    cve_id: str,
    severity: str,
    action: str,
    package_name: str | None = None,
    affected_version: str | None = None,
    reason: str | None = None,
) -> VulnGate:
    if severity not in VALID_VULN_SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(VALID_VULN_SEVERITIES)}")
    if action not in VALID_VULN_ACTIONS:
        raise ValueError(f"action must be one of {sorted(VALID_VULN_ACTIONS)}")
    get_compliance_profile(session, profile_id)
    existing = session.scalars(
        sa.select(VulnGate).where(
            VulnGate.profile_id == profile_id,
            VulnGate.cve_id == cve_id,
        )
    ).first()
    if existing:
        existing.severity = severity
        existing.action = action
        existing.package_name = package_name
        existing.affected_version = affected_version
        existing.reason = reason
        gate = existing
    else:
        gate = VulnGate(
            id=_uuid(),
            profile_id=profile_id,
            cve_id=cve_id,
            severity=severity,
            action=action,
            package_name=package_name,
            affected_version=affected_version,
            reason=reason,
        )
        session.add(gate)
    _invalidate(session, profile_id)
    session.flush()
    return gate


def list_vuln_gates(session: Session, profile_id: str) -> list[VulnGate]:
    get_compliance_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(VulnGate)
            .where(VulnGate.profile_id == profile_id)
            .order_by(VulnGate.cve_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# SBOM entries
# ---------------------------------------------------------------------------

def add_sbom_entry(
    session: Session,
    profile_id: str,
    package_name: str,
    package_version: str,
    spdx_id: str | None = None,
    purl: str | None = None,
    supplier: str | None = None,
    source_url: str | None = None,
    is_source_available: bool = True,
) -> SbomEntry:
    get_compliance_profile(session, profile_id)
    existing = session.scalars(
        sa.select(SbomEntry).where(
            SbomEntry.profile_id == profile_id,
            SbomEntry.package_name == package_name,
            SbomEntry.package_version == package_version,
        )
    ).first()
    if existing:
        existing.spdx_id = spdx_id
        existing.purl = purl
        existing.supplier = supplier
        existing.source_url = source_url
        existing.is_source_available = is_source_available
        entry = existing
    else:
        entry = SbomEntry(
            id=_uuid(),
            profile_id=profile_id,
            package_name=package_name,
            package_version=package_version,
            spdx_id=spdx_id,
            purl=purl,
            supplier=supplier,
            source_url=source_url,
            is_source_available=is_source_available,
        )
        session.add(entry)
    _invalidate(session, profile_id)
    session.flush()
    return entry


def list_sbom_entries(session: Session, profile_id: str) -> list[SbomEntry]:
    get_compliance_profile(session, profile_id)
    return list(
        session.scalars(
            sa.select(SbomEntry)
            .where(SbomEntry.profile_id == profile_id)
            .order_by(SbomEntry.package_name, SbomEntry.package_version)
        ).all()
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_compliance_report(
    session: Session, profile_id: str
) -> ComplianceProfile:
    profile = get_compliance_profile(session, profile_id)
    entries = list_sbom_entries(session, profile_id)
    gates = list_vuln_gates(session, profile_id)
    rules = list_license_rules(session, profile_id)

    sbom_text = _render_sbom(profile, entries)
    vuln_text = _render_vuln_report(profile, gates)
    lic_text = _render_license_report(profile, entries, rules)

    combined = "\n".join([sbom_text, vuln_text, lic_text])
    digest = hashlib.sha256(combined.encode()).hexdigest()
    content_hash = f"sha256:{digest}"

    profile.rendered_sbom = sbom_text
    profile.rendered_vuln_report = vuln_text
    profile.rendered_license_report = lic_text
    profile.content_hash = content_hash
    profile.rendered_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    session.flush()
    return profile


def _render_sbom(profile: ComplianceProfile, entries: list[SbomEntry]) -> str:
    lines: list[str] = [
        "SPDXVersion: SPDX-2.3",
        "DataLicense: CC0-1.0",
        f"SPDXID: SPDXRef-DOCUMENT",
        f"DocumentName: {profile.name}",
        f"DocumentNamespace: urn:osfabricum:compliance:{profile.id}",
        "",
        "## Packages",
        "",
    ]
    for e in entries:
        lines += [
            f"PackageName: {e.package_name}",
            f"PackageVersion: {e.package_version}",
        ]
        if e.spdx_id:
            lines.append(f"PackageLicenseDeclared: {e.spdx_id}")
        if e.purl:
            lines.append(f"ExternalRef: PACKAGE-MANAGER purl {e.purl}")
        if e.supplier:
            lines.append(f"PackageSupplier: {e.supplier}")
        if e.source_url:
            lines.append(f"PackageDownloadLocation: {e.source_url}")
        src_flag = "YES" if e.is_source_available else "NO"
        lines.append(f"FilesAnalyzed: {src_flag}")
        lines.append("")
    return "\n".join(lines)


def _render_vuln_report(profile: ComplianceProfile, gates: list[VulnGate]) -> str:
    threshold = profile.min_vuln_severity_to_block
    threshold_rank = _SEVERITY_RANK.get(threshold, 0)
    lines: list[str] = [
        "## Vulnerability Gate Report",
        f"# block-threshold: {threshold}",
        "",
    ]
    blocked: list[str] = []
    warned: list[str] = []
    for g in sorted(gates, key=lambda x: (x.cve_id,)):
        sev_rank = _SEVERITY_RANK.get(g.severity, 99)
        auto_blocked = sev_rank <= threshold_rank and g.action != "ignore"
        status = g.action.upper()
        if auto_blocked and g.action == "block":
            status = "BLOCK"
            blocked.append(g.cve_id)
        elif g.action == "warn":
            warned.append(g.cve_id)
            status = "WARN"
        elif g.action == "ignore":
            status = "IGNORE"
        pkg_note = ""
        if g.package_name:
            pkg_note = f" ({g.package_name}"
            if g.affected_version:
                pkg_note += f" {g.affected_version}"
            pkg_note += ")"
        reason_note = f" — {g.reason}" if g.reason else ""
        lines.append(
            f"{g.cve_id}  severity={g.severity}  action={status}{pkg_note}{reason_note}"
        )
    lines += [
        "",
        f"# blocked: {len(blocked)}  warned: {len(warned)}",
    ]
    if blocked:
        lines.append(f"# BUILD BLOCKED by: {', '.join(blocked)}")
    return "\n".join(lines)


def _render_license_report(
    profile: ComplianceProfile,
    entries: list[SbomEntry],
    rules: list[LicenseRule],
) -> str:
    rule_map = {r.spdx_id: r.policy for r in rules}
    lines: list[str] = [
        "## License Compliance Report",
        f"# allow-copyleft={profile.allow_copyleft}  allow-proprietary={profile.allow_proprietary}",
        "",
    ]
    failures: list[str] = []
    warnings: list[str] = []
    for e in entries:
        spdx = e.spdx_id or "LicenseRef-Unknown"
        policy = rule_map.get(spdx)
        if policy == "deny":
            verdict = "FAIL"
            failures.append(f"{e.package_name}:{spdx}")
        elif policy == "warn":
            verdict = "WARN"
            warnings.append(f"{e.package_name}:{spdx}")
        elif policy == "allow":
            verdict = "PASS"
        else:
            verdict = "PASS"
        lines.append(
            f"{e.package_name}@{e.package_version}  license={spdx}  verdict={verdict}"
        )
    lines += [
        "",
        f"# failures: {len(failures)}  warnings: {len(warnings)}",
    ]
    if failures:
        lines.append(f"# LICENSE DENIED: {', '.join(failures)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _invalidate(session: Session, profile_id: str) -> None:
    session.execute(
        sa.update(ComplianceProfile)
        .where(ComplianceProfile.id == profile_id)
        .values(content_hash=None, rendered_at=None, updated_at=_now())
    )
