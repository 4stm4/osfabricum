"""Unit tests for M48 — License / SBOM / Vuln / Source Compliance Designer."""

from __future__ import annotations

import pytest

from osfabricum import compliance as cmp
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_spdx_license_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine  # noqa: PLC0415

    url = f"sqlite:///{tmp_path}/test_compliance.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_spdx_license_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = cmp.create_compliance_profile(session, "test-policy")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# SPDX license kinds
# ---------------------------------------------------------------------------


def test_spdx_kinds_seeded(session):
    kinds = cmp.list_spdx_license_kinds(session)
    assert len(kinds) == 14


def test_spdx_kinds_ordered(session):
    kinds = cmp.list_spdx_license_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_spdx_kinds_copyleft_flags(session):
    kinds = {k.spdx_id: k for k in cmp.list_spdx_license_kinds(session)}
    assert kinds["GPL-3.0-only"].is_copyleft is True
    assert kinds["GPL-3.0-only"].is_permissive is False
    assert kinds["MIT"].is_copyleft is False
    assert kinds["MIT"].is_permissive is True


def test_spdx_seed_idempotent(session):
    count = seed_spdx_license_kinds(session)
    assert count == 0  # all already present


def test_spdx_proprietary_entry(session):
    kinds = {k.spdx_id: k for k in cmp.list_spdx_license_kinds(session)}
    assert "Proprietary" in kinds
    assert kinds["Proprietary"].is_copyleft is False
    assert kinds["Proprietary"].is_permissive is False


# ---------------------------------------------------------------------------
# Compliance profiles — CRUD
# ---------------------------------------------------------------------------


def test_create_profile(profile):
    assert profile.name == "test-policy"
    assert profile.allow_copyleft is True
    assert profile.allow_proprietary is False
    assert profile.min_vuln_severity_to_block == "critical"
    assert profile.require_sbom is True
    assert profile.content_hash is None


def test_create_profile_with_options(session):
    p = cmp.create_compliance_profile(
        session,
        "strict",
        allow_copyleft=False,
        allow_proprietary=False,
        min_vuln_severity_to_block="high",
        require_sbom=True,
    )
    session.commit()
    assert p.allow_copyleft is False
    assert p.min_vuln_severity_to_block == "high"


def test_list_profiles(session, profile):
    p2 = cmp.create_compliance_profile(session, "second-policy")
    session.commit()
    profiles = cmp.list_compliance_profiles(session)
    names = [p.name for p in profiles]
    assert "test-policy" in names
    assert "second-policy" in names


def test_get_profile(session, profile):
    fetched = cmp.get_compliance_profile(session, profile.id)
    assert fetched.id == profile.id


def test_get_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.get_compliance_profile(session, "no-such-id")


def test_create_duplicate_profile(session, profile):
    with pytest.raises(ValueError, match="already exists"):
        cmp.create_compliance_profile(session, "test-policy")


def test_create_profile_invalid_block_severity(session):
    with pytest.raises(ValueError, match="min_vuln_severity_to_block"):
        cmp.create_compliance_profile(
            session, "bad", min_vuln_severity_to_block="extreme"
        )


def test_update_profile(session, profile):
    cmp.update_compliance_profile(
        session, profile.id,
        allow_copyleft=False,
        min_vuln_severity_to_block="high",
    )
    session.commit()
    updated = cmp.get_compliance_profile(session, profile.id)
    assert updated.allow_copyleft is False
    assert updated.min_vuln_severity_to_block == "high"


def test_update_profile_clears_hash(session, profile):
    profile.content_hash = "sha256:abc"
    session.flush()
    cmp.update_compliance_profile(session, profile.id, description="updated")
    session.commit()
    fetched = cmp.get_compliance_profile(session, profile.id)
    assert fetched.content_hash is None


def test_update_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.update_compliance_profile(session, "no-such-id", description="x")


def test_update_profile_invalid_severity(session, profile):
    with pytest.raises(ValueError, match="min_vuln_severity_to_block"):
        cmp.update_compliance_profile(
            session, profile.id, min_vuln_severity_to_block="catastrophic"
        )


# ---------------------------------------------------------------------------
# License rules
# ---------------------------------------------------------------------------


def test_set_license_rule(session, profile):
    r = cmp.set_license_rule(session, profile.id, "MIT", "allow")
    session.commit()
    assert r.spdx_id == "MIT"
    assert r.policy == "allow"


def test_set_license_rule_upsert(session, profile):
    cmp.set_license_rule(session, profile.id, "GPL-3.0-only", "warn")
    session.commit()
    cmp.set_license_rule(session, profile.id, "GPL-3.0-only", "deny", "copyleft not permitted")
    session.commit()
    rules = cmp.list_license_rules(session, profile.id)
    gpl = next(r for r in rules if r.spdx_id == "GPL-3.0-only")
    assert gpl.policy == "deny"
    assert gpl.reason == "copyleft not permitted"


def test_set_license_rule_all_policies(session, profile):
    for policy in ("allow", "deny", "warn"):
        r = cmp.set_license_rule(session, profile.id, f"spdx-{policy}", policy)
        assert r.policy == policy


def test_set_license_rule_invalid_policy(session, profile):
    with pytest.raises(ValueError, match="policy"):
        cmp.set_license_rule(session, profile.id, "MIT", "ignore")


def test_set_license_rule_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.set_license_rule(session, "no-such-id", "MIT", "allow")


def test_list_license_rules_ordered(session, profile):
    for spdx in ("MIT", "Apache-2.0", "GPL-3.0-only"):
        cmp.set_license_rule(session, profile.id, spdx, "allow")
    session.commit()
    rules = cmp.list_license_rules(session, profile.id)
    ids = [r.spdx_id for r in rules]
    assert ids == sorted(ids)


def test_list_license_rules_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.list_license_rules(session, "no-such-id")


# ---------------------------------------------------------------------------
# Vuln gates
# ---------------------------------------------------------------------------


def test_set_vuln_gate(session, profile):
    g = cmp.set_vuln_gate(session, profile.id, "CVE-2024-1234", "critical", "block")
    session.commit()
    assert g.cve_id == "CVE-2024-1234"
    assert g.severity == "critical"
    assert g.action == "block"


def test_set_vuln_gate_upsert(session, profile):
    cmp.set_vuln_gate(session, profile.id, "CVE-2024-0001", "high", "warn")
    session.commit()
    cmp.set_vuln_gate(
        session, profile.id, "CVE-2024-0001", "critical", "block",
        package_name="openssl", reason="urgent"
    )
    session.commit()
    gates = cmp.list_vuln_gates(session, profile.id)
    g = next(x for x in gates if x.cve_id == "CVE-2024-0001")
    assert g.severity == "critical"
    assert g.action == "block"
    assert g.package_name == "openssl"


def test_set_vuln_gate_all_actions(session, profile):
    for i, action in enumerate(("block", "warn", "ignore")):
        g = cmp.set_vuln_gate(
            session, profile.id, f"CVE-2024-{i:04d}", "high", action
        )
        assert g.action == action


def test_set_vuln_gate_invalid_action(session, profile):
    with pytest.raises(ValueError, match="action"):
        cmp.set_vuln_gate(session, profile.id, "CVE-2024-9999", "high", "skip")


def test_set_vuln_gate_invalid_severity(session, profile):
    with pytest.raises(ValueError, match="severity"):
        cmp.set_vuln_gate(session, profile.id, "CVE-2024-9999", "catastrophic", "block")


def test_set_vuln_gate_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.set_vuln_gate(session, "no-such-id", "CVE-2024-1", "high", "block")


def test_list_vuln_gates_ordered(session, profile):
    for cve in ("CVE-2024-0003", "CVE-2024-0001", "CVE-2024-0002"):
        cmp.set_vuln_gate(session, profile.id, cve, "high", "warn")
    session.commit()
    gates = cmp.list_vuln_gates(session, profile.id)
    ids = [g.cve_id for g in gates]
    assert ids == sorted(ids)


def test_list_vuln_gates_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.list_vuln_gates(session, "no-such-id")


# ---------------------------------------------------------------------------
# SBOM entries
# ---------------------------------------------------------------------------


def test_add_sbom_entry(session, profile):
    e = cmp.add_sbom_entry(session, profile.id, "openssl", "3.0.7", spdx_id="Apache-2.0")
    session.commit()
    assert e.package_name == "openssl"
    assert e.package_version == "3.0.7"
    assert e.spdx_id == "Apache-2.0"
    assert e.is_source_available is True


def test_add_sbom_entry_upsert(session, profile):
    cmp.add_sbom_entry(session, profile.id, "curl", "8.1.0")
    session.commit()
    cmp.add_sbom_entry(
        session, profile.id, "curl", "8.1.0",
        spdx_id="MIT", purl="pkg:deb/curl@8.1.0"
    )
    session.commit()
    entries = cmp.list_sbom_entries(session, profile.id)
    curl = next(e for e in entries if e.package_name == "curl")
    assert curl.spdx_id == "MIT"
    assert curl.purl == "pkg:deb/curl@8.1.0"


def test_add_sbom_entry_multiple(session, profile):
    for pkg in ("libz", "glibc", "busybox"):
        cmp.add_sbom_entry(session, profile.id, pkg, "1.0.0")
    session.commit()
    entries = cmp.list_sbom_entries(session, profile.id)
    assert len(entries) == 3


def test_list_sbom_entries_ordered(session, profile):
    for pkg in ("zlib", "curl", "openssl"):
        cmp.add_sbom_entry(session, profile.id, pkg, "1.0")
    session.commit()
    entries = cmp.list_sbom_entries(session, profile.id)
    names = [e.package_name for e in entries]
    assert names == sorted(names)


def test_add_sbom_entry_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.add_sbom_entry(session, "no-such-id", "openssl", "1.0")


def test_list_sbom_entries_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.list_sbom_entries(session, "no-such-id")


# ---------------------------------------------------------------------------
# Render — SBOM
# ---------------------------------------------------------------------------


def test_render_empty(session, profile):
    p = cmp.render_compliance_report(session, profile.id)
    assert p.content_hash is not None
    assert p.content_hash.startswith("sha256:")
    assert p.rendered_sbom is not None
    assert p.rendered_vuln_report is not None
    assert p.rendered_license_report is not None


def test_render_sbom_header(session, profile):
    p = cmp.render_compliance_report(session, profile.id)
    assert "SPDXVersion: SPDX-2.3" in p.rendered_sbom
    assert f"DocumentName: {profile.name}" in p.rendered_sbom


def test_render_sbom_package_content(session, profile):
    cmp.add_sbom_entry(
        session, profile.id, "openssl", "3.0.7",
        spdx_id="Apache-2.0", purl="pkg:deb/openssl@3.0.7",
        supplier="OpenSSL Foundation",
    )
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "openssl" in p.rendered_sbom
    assert "3.0.7" in p.rendered_sbom
    assert "Apache-2.0" in p.rendered_sbom
    assert "pkg:deb/openssl@3.0.7" in p.rendered_sbom
    assert "OpenSSL Foundation" in p.rendered_sbom


def test_render_sbom_source_flag(session, profile):
    cmp.add_sbom_entry(
        session, profile.id, "binary-blob", "1.0", is_source_available=False
    )
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "FilesAnalyzed: NO" in p.rendered_sbom


# ---------------------------------------------------------------------------
# Render — Vuln report
# ---------------------------------------------------------------------------


def test_render_vuln_header(session, profile):
    p = cmp.render_compliance_report(session, profile.id)
    assert "Vulnerability Gate Report" in p.rendered_vuln_report
    assert "block-threshold: critical" in p.rendered_vuln_report


def test_render_vuln_blocked_cve(session, profile):
    cmp.set_vuln_gate(session, profile.id, "CVE-2024-9999", "critical", "block")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "CVE-2024-9999" in p.rendered_vuln_report
    assert "BLOCK" in p.rendered_vuln_report
    assert "BUILD BLOCKED" in p.rendered_vuln_report


def test_render_vuln_ignored(session, profile):
    cmp.set_vuln_gate(session, profile.id, "CVE-2024-0001", "low", "ignore")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "IGNORE" in p.rendered_vuln_report


def test_render_vuln_warn(session, profile):
    cmp.set_vuln_gate(session, profile.id, "CVE-2024-0002", "high", "warn")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "WARN" in p.rendered_vuln_report


def test_render_vuln_package_note(session, profile):
    cmp.set_vuln_gate(
        session, profile.id, "CVE-2024-0003", "high", "block",
        package_name="libssl", affected_version="3.0.0"
    )
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "libssl" in p.rendered_vuln_report
    assert "3.0.0" in p.rendered_vuln_report


def test_render_vuln_sorted_by_cve(session, profile):
    for cve in ("CVE-2024-0003", "CVE-2024-0001", "CVE-2024-0002"):
        cmp.set_vuln_gate(session, profile.id, cve, "high", "warn")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    lines = [ln for ln in p.rendered_vuln_report.splitlines() if "CVE-" in ln]
    cves = [ln.split()[0] for ln in lines]
    assert cves == sorted(cves)


# ---------------------------------------------------------------------------
# Render — License report
# ---------------------------------------------------------------------------


def test_render_license_header(session, profile):
    p = cmp.render_compliance_report(session, profile.id)
    assert "License Compliance Report" in p.rendered_license_report
    assert "allow-copyleft=True" in p.rendered_license_report


def test_render_license_pass(session, profile):
    cmp.add_sbom_entry(session, profile.id, "curl", "8.0", spdx_id="MIT")
    cmp.set_license_rule(session, profile.id, "MIT", "allow")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "PASS" in p.rendered_license_report


def test_render_license_deny(session, profile):
    cmp.add_sbom_entry(session, profile.id, "gpl-tool", "1.0", spdx_id="GPL-3.0-only")
    cmp.set_license_rule(session, profile.id, "GPL-3.0-only", "deny")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "FAIL" in p.rendered_license_report
    assert "LICENSE DENIED" in p.rendered_license_report


def test_render_license_warn(session, profile):
    cmp.add_sbom_entry(session, profile.id, "lgpl-lib", "2.0", spdx_id="LGPL-2.1-only")
    cmp.set_license_rule(session, profile.id, "LGPL-2.1-only", "warn")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    assert "WARN" in p.rendered_license_report


def test_render_license_no_rule_passes(session, profile):
    cmp.add_sbom_entry(session, profile.id, "no-rule-pkg", "1.0", spdx_id="ISC")
    session.flush()
    p = cmp.render_compliance_report(session, profile.id)
    lines = [ln for ln in p.rendered_license_report.splitlines() if "no-rule-pkg" in ln]
    assert any("PASS" in ln for ln in lines)


# ---------------------------------------------------------------------------
# Render — determinism and cache
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    cmp.add_sbom_entry(session, profile.id, "libz", "1.3", spdx_id="Zlib")
    session.flush()
    p1 = cmp.render_compliance_report(session, profile.id)
    hash1 = p1.content_hash
    p2 = cmp.render_compliance_report(session, profile.id)
    assert p2.content_hash == hash1


def test_render_stored(session, profile):
    p = cmp.render_compliance_report(session, profile.id)
    session.commit()
    fetched = cmp.get_compliance_profile(session, profile.id)
    assert fetched.content_hash == p.content_hash
    assert fetched.rendered_sbom is not None


def test_render_hash_changes_on_new_entry(session, profile):
    p1 = cmp.render_compliance_report(session, profile.id)
    h1 = p1.content_hash
    cmp.add_sbom_entry(session, profile.id, "extra-pkg", "0.1")
    session.flush()
    p2 = cmp.render_compliance_report(session, profile.id)
    assert p2.content_hash != h1


def test_add_entry_clears_hash(session, profile):
    cmp.render_compliance_report(session, profile.id)
    session.flush()
    cmp.add_sbom_entry(session, profile.id, "new-pkg", "1.0")
    session.flush()
    fetched = cmp.get_compliance_profile(session, profile.id)
    assert fetched.content_hash is None


def test_set_gate_clears_hash(session, profile):
    cmp.render_compliance_report(session, profile.id)
    session.flush()
    cmp.set_vuln_gate(session, profile.id, "CVE-2024-1111", "high", "warn")
    session.flush()
    fetched = cmp.get_compliance_profile(session, profile.id)
    assert fetched.content_hash is None


def test_render_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        cmp.render_compliance_report(session, "no-such-id")
