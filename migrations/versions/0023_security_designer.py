"""M47 — Security / Hardening Designer.

Creates: security_mac_kinds, extends security_profiles, sysctl_settings,
mac_rules, pam_rules, capability_grants.
Seeds 6 MAC framework kinds.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "security_mac_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "security_mac_kinds",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    # Extend existing security_profiles stub with M47 columns
    existing_cols = {
        col["name"] for col in sa.inspect(bind).get_columns("security_profiles")
    }
    for col_name, col_def in [
        ("mac_policy", sa.Column("mac_policy", sa.String(32), nullable=False, server_default="none")),
        ("description", sa.Column("description", sa.Text, nullable=False, server_default="")),
        ("rendered_sysctl", sa.Column("rendered_sysctl", sa.Text, nullable=True)),
        ("rendered_mac_rules", sa.Column("rendered_mac_rules", sa.Text, nullable=True)),
        ("rendered_pam_config", sa.Column("rendered_pam_config", sa.Text, nullable=True)),
        ("rendered_capabilities", sa.Column("rendered_capabilities", sa.Text, nullable=True)),
        ("content_hash", sa.Column("content_hash", sa.String(71), nullable=True)),
        ("rendered_at", sa.Column("rendered_at", sa.DateTime, nullable=True)),
        ("created_at", sa.Column("created_at", sa.DateTime, nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime, nullable=True)),
    ]:
        if col_name not in existing_cols:
            op.add_column("security_profiles", col_def)

    # Drop metadata_json if it exists (was the stub column)
    if "metadata_json" in existing_cols:
        with op.batch_alter_table("security_profiles") as batch_op:
            batch_op.drop_column("metadata_json")

    op.create_table(
        "sysctl_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("security_profiles.id"),
            nullable=False,
        ),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.UniqueConstraint("profile_id", "key", name="uq_sysctl_settings_profile_key"),
    )
    op.create_index("ix_sysctl_settings_profile_id", "sysctl_settings", ["profile_id"])

    op.create_table(
        "mac_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("security_profiles.id"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("rule_text", sa.Text, nullable=False),
        sa.Column("is_enforcing", sa.Boolean, nullable=False, default=True),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.Column("comment", sa.String(128), nullable=True),
    )
    op.create_index("ix_mac_rules_profile_id", "mac_rules", ["profile_id"])

    op.create_table(
        "pam_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("security_profiles.id"),
            nullable=False,
        ),
        sa.Column("service", sa.String(64), nullable=False),
        sa.Column("module_type", sa.String(16), nullable=False),
        sa.Column("control_flag", sa.String(24), nullable=False),
        sa.Column("module_path", sa.String(128), nullable=False),
        sa.Column("module_args", sa.Text, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.UniqueConstraint(
            "profile_id", "service", "module_type", "module_path",
            name="uq_pam_rules_profile_svc_type_module",
        ),
    )
    op.create_index("ix_pam_rules_profile_id", "pam_rules", ["profile_id"])

    op.create_table(
        "capability_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("security_profiles.id"),
            nullable=False,
        ),
        sa.Column("executable", sa.String(256), nullable=False),
        sa.Column("add_caps", sa.Text, nullable=True),
        sa.Column("drop_caps", sa.Text, nullable=True),
        sa.Column("no_new_privs", sa.Boolean, nullable=False, default=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.UniqueConstraint(
            "profile_id", "executable", name="uq_capability_grants_profile_exec"
        ),
    )
    op.create_index(
        "ix_capability_grants_profile_id", "capability_grants", ["profile_id"]
    )

    # Seed MAC kinds
    from osfabricum.db.seed_data import SECURITY_MAC_KINDS  # noqa: PLC0415

    kind_table = sa.table(
        "security_mac_kinds",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM security_mac_kinds")
        ).fetchall()
    }
    for name, description, display_order in SECURITY_MAC_KINDS:
        if name in existing:
            continue
        bind.execute(
            kind_table.insert().values(
                name=name, description=description, display_order=display_order
            )
        )


def downgrade() -> None:
    for tbl in (
        "capability_grants",
        "pam_rules",
        "mac_rules",
        "sysctl_settings",
        "security_mac_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
