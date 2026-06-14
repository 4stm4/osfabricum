"""M42 — Desktop Integration Designer.

Creates: mime_type_definitions, desktop_integration_profiles,
         mime_associations, autostart_entries, xdg_user_dirs.
Seeds 21 MIME type definitions.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "mime_type_definitions" not in existing_tables

    if not fresh:
        return  # tables already created by create_all (fresh install)

    op.create_table(
        "mime_type_definitions",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("parent", sa.String(128), nullable=True),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "desktop_integration_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("xdg_data_dirs", sa.JSON, nullable=False, default=list),
        sa.Column("xdg_config_dirs", sa.JSON, nullable=False, default=list),
        sa.Column("rendered_mimeapps", sa.Text, nullable=True),
        sa.Column("rendered_user_dirs", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id",
            "name",
            name="uq_desktop_integration_profiles_dist_name",
        ),
    )
    op.create_index(
        "ix_desktop_integration_profiles_distribution_id",
        "desktop_integration_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "mime_associations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("desktop_integration_profiles.id"),
            nullable=False,
        ),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("desktop_file", sa.String(128), nullable=False),
        sa.Column("association_type", sa.String(16), nullable=False, default="default"),
        sa.Column("priority", sa.Integer, nullable=False, default=0),
        sa.UniqueConstraint(
            "profile_id",
            "mime_type",
            "desktop_file",
            name="uq_mime_associations_profile_mime_desktop",
        ),
    )
    op.create_index(
        "ix_mime_associations_profile_id", "mime_associations", ["profile_id"]
    )

    op.create_table(
        "autostart_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("desktop_integration_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("exec_cmd", sa.String(256), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("condition", sa.String(16), nullable=False, default="always"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("desktop_entry", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "profile_id", "name", name="uq_autostart_entries_profile_name"
        ),
    )
    op.create_index(
        "ix_autostart_entries_profile_id", "autostart_entries", ["profile_id"]
    )

    op.create_table(
        "xdg_user_dirs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("desktop_integration_profiles.id"),
            nullable=False,
        ),
        sa.Column("dir_name", sa.String(32), nullable=False),
        sa.Column("path", sa.String(256), nullable=False),
        sa.UniqueConstraint(
            "profile_id", "dir_name", name="uq_xdg_user_dirs_profile_dir"
        ),
    )
    op.create_index(
        "ix_xdg_user_dirs_profile_id", "xdg_user_dirs", ["profile_id"]
    )

    # Seed MIME type definitions
    from osfabricum.db.seed_data import MIME_TYPE_DEFINITIONS  # noqa: PLC0415

    mime_table = sa.table(
        "mime_type_definitions",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("parent", sa.String),
        sa.column("icon", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM mime_type_definitions")
        ).fetchall()
    }
    for name, description, parent, icon, display_order in MIME_TYPE_DEFINITIONS:
        if name in existing:
            continue
        bind.execute(
            mime_table.insert().values(
                name=name,
                description=description,
                parent=parent,
                icon=icon,
                display_order=display_order,
            )
        )


def downgrade() -> None:
    for tbl in (
        "xdg_user_dirs",
        "autostart_entries",
        "mime_associations",
        "desktop_integration_profiles",
        "mime_type_definitions",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
