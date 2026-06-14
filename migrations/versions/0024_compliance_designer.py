"""M48 — License / SBOM / Vuln / Source Compliance Designer.

Creates: spdx_license_kinds, compliance_profiles, license_rules,
vuln_gates, sbom_entries.
Seeds 14 SPDX license identifiers.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "spdx_license_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "spdx_license_kinds",
        sa.Column("spdx_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, default=""),
        sa.Column("is_copyleft", sa.Boolean, nullable=False, default=False),
        sa.Column("is_permissive", sa.Boolean, nullable=False, default=False),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "compliance_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("allow_copyleft", sa.Boolean, nullable=False, default=True),
        sa.Column("allow_proprietary", sa.Boolean, nullable=False, default=False),
        sa.Column(
            "min_vuln_severity_to_block",
            sa.String(16),
            nullable=False,
            default="critical",
        ),
        sa.Column("require_sbom", sa.Boolean, nullable=False, default=True),
        sa.Column("rendered_sbom", sa.Text, nullable=True),
        sa.Column("rendered_vuln_report", sa.Text, nullable=True),
        sa.Column("rendered_license_report", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_compliance_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_compliance_profiles_distribution_id",
        "compliance_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "license_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("compliance_profiles.id"),
            nullable=False,
        ),
        sa.Column("spdx_id", sa.String(64), nullable=False),
        sa.Column("policy", sa.String(8), nullable=False, default="allow"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "profile_id", "spdx_id", name="uq_license_rules_profile_spdx"
        ),
    )
    op.create_index("ix_license_rules_profile_id", "license_rules", ["profile_id"])

    op.create_table(
        "vuln_gates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("compliance_profiles.id"),
            nullable=False,
        ),
        sa.Column("cve_id", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, default="high"),
        sa.Column("action", sa.String(8), nullable=False, default="block"),
        sa.Column("package_name", sa.String(128), nullable=True),
        sa.Column("affected_version", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "profile_id", "cve_id", name="uq_vuln_gates_profile_cve"
        ),
    )
    op.create_index("ix_vuln_gates_profile_id", "vuln_gates", ["profile_id"])

    op.create_table(
        "sbom_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("compliance_profiles.id"),
            nullable=False,
        ),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("package_version", sa.String(64), nullable=False),
        sa.Column("spdx_id", sa.String(64), nullable=True),
        sa.Column("purl", sa.String(256), nullable=True),
        sa.Column("supplier", sa.String(128), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("is_source_available", sa.Boolean, nullable=False, default=True),
        sa.UniqueConstraint(
            "profile_id", "package_name", "package_version",
            name="uq_sbom_entries_profile_pkg_ver",
        ),
    )
    op.create_index("ix_sbom_entries_profile_id", "sbom_entries", ["profile_id"])

    # Seed SPDX license kinds
    from osfabricum.db.seed_data import SPDX_LICENSE_KINDS  # noqa: PLC0415

    lic_table = sa.table(
        "spdx_license_kinds",
        sa.column("spdx_id", sa.String),
        sa.column("name", sa.String),
        sa.column("is_copyleft", sa.Boolean),
        sa.column("is_permissive", sa.Boolean),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT spdx_id FROM spdx_license_kinds")
        ).fetchall()
    }
    for spdx_id, name, is_copyleft, is_permissive, display_order in SPDX_LICENSE_KINDS:
        if spdx_id in existing:
            continue
        bind.execute(
            lic_table.insert().values(
                spdx_id=spdx_id,
                name=name,
                is_copyleft=is_copyleft,
                is_permissive=is_permissive,
                display_order=display_order,
            )
        )


def downgrade() -> None:
    for tbl in (
        "sbom_entries",
        "vuln_gates",
        "license_rules",
        "compliance_profiles",
        "spdx_license_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
