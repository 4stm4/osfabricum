"""M49 — Update / OTA / Recovery Designer.

Creates: update_strategy_kinds, update_profiles, update_channels,
recovery_targets, update_hooks.
Seeds 6 update strategy kinds.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "update_strategy_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "update_strategy_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, default=""),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "update_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("strategy", sa.String(32), nullable=False, default="full"),
        sa.Column("signing_required", sa.Boolean, nullable=False, default=True),
        sa.Column("rollback_enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("rollback_window_days", sa.Integer, nullable=False, default=30),
        sa.Column("max_delta_size_mb", sa.Integer, nullable=True),
        sa.Column("verification_mode", sa.String(16), nullable=False, default="strict"),
        sa.Column("rendered_update_config", sa.Text, nullable=True),
        sa.Column("rendered_recovery_config", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_update_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_update_profiles_distribution_id",
        "update_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "update_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("update_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("signing_key_id", sa.String(128), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, default=0),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.UniqueConstraint(
            "profile_id", "name", name="uq_update_channels_profile_name"
        ),
    )
    op.create_index(
        "ix_update_channels_profile_id", "update_channels", ["profile_id"]
    )

    op.create_table(
        "recovery_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("update_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False, default="minimal"),
        sa.Column("kernel_args", sa.Text, nullable=True),
        sa.Column("initramfs_hint", sa.String(256), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.Column("priority", sa.Integer, nullable=False, default=0),
        sa.UniqueConstraint(
            "profile_id", "name", name="uq_recovery_targets_profile_name"
        ),
    )
    op.create_index(
        "ix_recovery_targets_profile_id", "recovery_targets", ["profile_id"]
    )

    op.create_table(
        "update_hooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("update_profiles.id"),
            nullable=False,
        ),
        sa.Column("hook_point", sa.String(32), nullable=False),
        sa.Column("script_content", sa.Text, nullable=False, default=""),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("priority", sa.Integer, nullable=False, default=0),
        sa.UniqueConstraint(
            "profile_id", "hook_point", "priority",
            name="uq_update_hooks_profile_point_prio",
        ),
    )
    op.create_index(
        "ix_update_hooks_profile_id", "update_hooks", ["profile_id"]
    )

    # Seed update strategy kinds
    from osfabricum.db.seed_data import UPDATE_STRATEGY_KINDS  # noqa: PLC0415

    sk_table = sa.table(
        "update_strategy_kinds",
        sa.column("kind", sa.String),
        sa.column("label", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT kind FROM update_strategy_kinds")
        ).fetchall()
    }
    for kind, label, description, display_order in UPDATE_STRATEGY_KINDS:
        if kind in existing:
            continue
        bind.execute(
            sk_table.insert().values(
                kind=kind,
                label=label,
                description=description,
                display_order=display_order,
            )
        )


def downgrade() -> None:
    for tbl in (
        "update_hooks",
        "recovery_targets",
        "update_channels",
        "update_profiles",
        "update_strategy_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
