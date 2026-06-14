"""M44 — Users / Groups / Credentials / Secrets Designer.

Creates: user_shell_kinds, os_user_profiles, os_groups, os_users,
user_supplementary_groups, secret_variables.
Seeds 7 login shell kinds.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "user_shell_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "user_shell_kinds",
        sa.Column("path", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "os_user_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("rendered_passwd", sa.Text, nullable=True),
        sa.Column("rendered_group", sa.Text, nullable=True),
        sa.Column("rendered_secrets_manifest", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_os_user_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_os_user_profiles_distribution_id",
        "os_user_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "os_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("os_user_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("gid", sa.Integer, nullable=True),
        sa.Column("is_system", sa.Boolean, nullable=False, default=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.UniqueConstraint("profile_id", "name", name="uq_os_groups_profile_name"),
    )
    op.create_index("ix_os_groups_profile_id", "os_groups", ["profile_id"])

    op.create_table(
        "os_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("os_user_profiles.id"),
            nullable=False,
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("uid", sa.Integer, nullable=True),
        sa.Column("primary_group", sa.String(64), nullable=False, default="users"),
        sa.Column("home_dir", sa.String(256), nullable=False),
        sa.Column("shell", sa.String(64), nullable=False, default="/bin/bash"),
        sa.Column("gecos", sa.String(128), nullable=False, default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, default=False),
        sa.Column("is_locked", sa.Boolean, nullable=False, default=False),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.UniqueConstraint(
            "profile_id", "username", name="uq_os_users_profile_username"
        ),
    )
    op.create_index("ix_os_users_profile_id", "os_users", ["profile_id"])

    op.create_table(
        "user_supplementary_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("os_users.id"),
            nullable=False,
        ),
        sa.Column("group_name", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "user_id", "group_name", name="uq_user_supplementary_groups_user_group"
        ),
    )
    op.create_index(
        "ix_user_supplementary_groups_user_id",
        "user_supplementary_groups",
        ["user_id"],
    )

    op.create_table(
        "secret_variables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("os_user_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("masked_value", sa.String(256), nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, default=True),
        sa.UniqueConstraint(
            "profile_id", "name", name="uq_secret_variables_profile_name"
        ),
    )
    op.create_index(
        "ix_secret_variables_profile_id", "secret_variables", ["profile_id"]
    )

    # Seed login shell kinds
    from osfabricum.db.seed_data import USER_SHELL_KINDS  # noqa: PLC0415

    shell_table = sa.table(
        "user_shell_kinds",
        sa.column("path", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing_shells = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT path FROM user_shell_kinds")
        ).fetchall()
    }
    for path, description, display_order in USER_SHELL_KINDS:
        if path in existing_shells:
            continue
        bind.execute(
            shell_table.insert().values(
                path=path, description=description, display_order=display_order
            )
        )


def downgrade() -> None:
    for tbl in (
        "secret_variables",
        "user_supplementary_groups",
        "os_users",
        "os_groups",
        "os_user_profiles",
        "user_shell_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
