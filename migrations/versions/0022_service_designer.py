"""M46 — Service / Init / Device Manager Designer.

Creates: init_system_kinds, service_profiles, service_entries,
device_rules, systemd_unit_overrides.
Seeds 7 init system kinds.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "init_system_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "init_system_kinds",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "service_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("init_system", sa.String(32), nullable=False, default="systemd"),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("rendered_units", sa.Text, nullable=True),
        sa.Column("rendered_udev", sa.Text, nullable=True),
        sa.Column("rendered_overrides", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_service_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_service_profiles_distribution_id",
        "service_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "service_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("service_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("unit_type", sa.String(16), nullable=False, default="service"),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("exec_start", sa.Text, nullable=True),
        sa.Column("exec_stop", sa.Text, nullable=True),
        sa.Column("exec_pre_start", sa.Text, nullable=True),
        sa.Column("restart_policy", sa.String(20), nullable=False, default="no"),
        sa.Column("wanted_by", sa.String(64), nullable=False, default="multi-user.target"),
        sa.Column("after", sa.Text, nullable=True),
        sa.Column("requires", sa.Text, nullable=True),
        sa.Column("environment", sa.Text, nullable=True),
        sa.Column("working_directory", sa.String(256), nullable=True),
        sa.Column("run_user", sa.String(64), nullable=True),
        sa.Column("run_group", sa.String(64), nullable=True),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("is_masked", sa.Boolean, nullable=False, default=False),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.UniqueConstraint(
            "profile_id", "name", "unit_type",
            name="uq_service_entries_profile_name_type",
        ),
    )
    op.create_index(
        "ix_service_entries_profile_id", "service_entries", ["profile_id"]
    )

    op.create_table(
        "device_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("service_profiles.id"),
            nullable=False,
        ),
        sa.Column("subsystem", sa.String(32), nullable=True),
        sa.Column("kernel_pattern", sa.String(64), nullable=True),
        sa.Column("attr_filter", sa.Text, nullable=True),
        sa.Column("udev_action", sa.String(16), nullable=False, default="add"),
        sa.Column("symlink", sa.String(128), nullable=True),
        sa.Column("mode", sa.String(8), nullable=True),
        sa.Column("owner", sa.String(64), nullable=True),
        sa.Column("group_name", sa.String(64), nullable=True),
        sa.Column("run_command", sa.Text, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, default=90),
        sa.Column("comment", sa.String(128), nullable=True),
    )
    op.create_index("ix_device_rules_profile_id", "device_rules", ["profile_id"])

    op.create_table(
        "systemd_unit_overrides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("service_profiles.id"),
            nullable=False,
        ),
        sa.Column("unit_name", sa.String(128), nullable=False),
        sa.Column("section", sa.String(32), nullable=False, default="Service"),
        sa.Column("override_content", sa.Text, nullable=False, default=""),
        sa.UniqueConstraint(
            "profile_id", "unit_name", name="uq_systemd_unit_overrides_profile_unit"
        ),
    )
    op.create_index(
        "ix_systemd_unit_overrides_profile_id",
        "systemd_unit_overrides",
        ["profile_id"],
    )

    # Seed init system kinds
    from osfabricum.db.seed_data import INIT_SYSTEM_KINDS  # noqa: PLC0415

    kind_table = sa.table(
        "init_system_kinds",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM init_system_kinds")
        ).fetchall()
    }
    for name, description, display_order in INIT_SYSTEM_KINDS:
        if name in existing:
            continue
        bind.execute(
            kind_table.insert().values(
                name=name, description=description, display_order=display_order
            )
        )


def downgrade() -> None:
    for tbl in (
        "systemd_unit_overrides",
        "device_rules",
        "service_entries",
        "service_profiles",
        "init_system_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
