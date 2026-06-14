"""M43 — Themes / Icons / Fonts Designer.

Creates: theme_asset_kinds, theme_profiles, theme_packages, gsettings_overrides.
Seeds 6 theme asset kinds.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "theme_asset_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "theme_asset_kinds",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "theme_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("gtk_theme", sa.String(64), nullable=False, default="Adwaita"),
        sa.Column("icon_theme", sa.String(64), nullable=False, default="Adwaita"),
        sa.Column("cursor_theme", sa.String(64), nullable=False, default="Adwaita"),
        sa.Column("sound_theme", sa.String(64), nullable=False, default="freedesktop"),
        sa.Column("dark_mode", sa.Boolean, nullable=False, default=False),
        sa.Column("font_default", sa.String(128), nullable=False, default="Sans"),
        sa.Column("font_monospace", sa.String(128), nullable=False, default="Monospace"),
        sa.Column("font_document", sa.String(128), nullable=False, default="Sans"),
        sa.Column("font_size", sa.Integer, nullable=False, default=11),
        sa.Column("cursor_size", sa.Integer, nullable=False, default=24),
        sa.Column("scaling_factor", sa.Float, nullable=False, default=1.0),
        sa.Column("rendered_gsettings", sa.Text, nullable=True),
        sa.Column("rendered_gtk_ini", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_theme_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_theme_profiles_distribution_id", "theme_profiles", ["distribution_id"]
    )

    op.create_table(
        "theme_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("theme_profiles.id"),
            nullable=False,
        ),
        sa.Column("asset_kind", sa.String(32), nullable=False),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("version_constraint", sa.String(64), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.UniqueConstraint(
            "profile_id",
            "asset_kind",
            "package_name",
            name="uq_theme_packages_profile_kind_pkg",
        ),
    )
    op.create_index(
        "ix_theme_packages_profile_id", "theme_packages", ["profile_id"]
    )

    op.create_table(
        "gsettings_overrides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("theme_profiles.id"),
            nullable=False,
        ),
        sa.Column("schema", sa.String(128), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "profile_id",
            "schema",
            "key",
            name="uq_gsettings_overrides_profile_schema_key",
        ),
    )
    op.create_index(
        "ix_gsettings_overrides_profile_id", "gsettings_overrides", ["profile_id"]
    )

    # Seed theme asset kinds
    from osfabricum.db.seed_data import THEME_ASSET_KINDS  # noqa: PLC0415

    kind_table = sa.table(
        "theme_asset_kinds",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM theme_asset_kinds")
        ).fetchall()
    }
    for name, description, display_order in THEME_ASSET_KINDS:
        if name in existing:
            continue
        bind.execute(
            kind_table.insert().values(
                name=name, description=description, display_order=display_order
            )
        )


def downgrade() -> None:
    for tbl in (
        "gsettings_overrides",
        "theme_packages",
        "theme_profiles",
        "theme_asset_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
