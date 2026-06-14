"""M48 — License / SBOM / Vuln / Source Compliance Designer."""

from osfabricum.compliance.service import (
    VALID_BLOCK_THRESHOLDS,
    VALID_LICENSE_POLICIES,
    VALID_VULN_ACTIONS,
    VALID_VULN_SEVERITIES,
    add_sbom_entry,
    create_compliance_profile,
    get_compliance_profile,
    list_compliance_profiles,
    list_license_rules,
    list_sbom_entries,
    list_spdx_license_kinds,
    list_vuln_gates,
    render_compliance_report,
    set_license_rule,
    set_vuln_gate,
    update_compliance_profile,
)

__all__ = [
    "VALID_BLOCK_THRESHOLDS",
    "VALID_LICENSE_POLICIES",
    "VALID_VULN_ACTIONS",
    "VALID_VULN_SEVERITIES",
    "add_sbom_entry",
    "create_compliance_profile",
    "get_compliance_profile",
    "list_compliance_profiles",
    "list_license_rules",
    "list_sbom_entries",
    "list_spdx_license_kinds",
    "list_vuln_gates",
    "render_compliance_report",
    "set_license_rule",
    "set_vuln_gate",
    "update_compliance_profile",
]
