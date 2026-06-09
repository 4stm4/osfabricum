"""M39 — Branding / Identity Designer.

Extends branding_profiles with os-release identity fields and rendered-artifact
columns. Creates: branding_assets, branding_targets, os_release_templates,
motd_templates, wallpaper_sets, boot_splash_themes, login_screen_themes.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# New columns added to branding_profiles (name → type)
_NEW_COLS: list[tuple[str, sa.types.TypeEngine]] = [
    ("os_name", sa.String(128)),
    ("os_id", sa.String(64)),
    ("os_version", sa.String(64)),
    ("os_pretty_name", sa.String(256)),
    ("os_home_url", sa.String(512)),
    ("vendor_name", sa.String(128)),
    ("vendor_url", sa.String(512)),
    ("support_url", sa.String(512)),
    ("bug_report_url", sa.String(512)),
    ("logo_asset_id", sa.String(36)),
    ("icon_asset_id", sa.String(36)),
    ("rendered_os_release", sa.Text),
    ("rendered_motd", sa.Text),
    ("content_hash", sa.String(128)),
    ("rendered_at", sa.DateTime),
    ("created_at", sa.DateTime),
    ("updated_at", sa.DateTime),
]


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    fresh = "branding_assets" not in existing_tables

    # Extend branding_profiles (guarded per column)
    existing_cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("branding_profiles")}
    for col_name, col_type in _NEW_COLS:
        if col_name not in existing_cols:
            op.add_column("branding_profiles", sa.Column(col_name, col_type, nullable=True))

    if not fresh:
        return  # new tables already created by create_all

    op.create_table(
        "branding_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("asset_kind", sa.String(32), nullable=False),
        sa.Column("source_path", sa.String(512), nullable=True),
        sa.Column("artifact_id", sa.String(36), nullable=True),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("width_px", sa.Integer, nullable=True),
        sa.Column("height_px", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "branding_profile_id", "name", name="uq_branding_assets_profile_name"
        ),
    )
    op.create_index("ix_branding_assets_profile_id", "branding_assets", ["branding_profile_id"])

    op.create_table(
        "branding_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=True),
        sa.Column("config_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "branding_profile_id", "stage", name="uq_branding_targets_profile_stage"
        ),
    )
    op.create_index(
        "ix_branding_targets_profile_id", "branding_targets", ["branding_profile_id"]
    )

    op.create_table(
        "os_release_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("template_text", sa.Text, nullable=False),
        sa.Column("rendered_text", sa.Text, nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "motd_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("template_text", sa.Text, nullable=False),
        sa.Column("rendered_text", sa.Text, nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "wallpaper_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("resolution", sa.String(16), nullable=True),
        sa.Column("asset_id", sa.String(36), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_wallpaper_sets_profile_id", "wallpaper_sets", ["branding_profile_id"])

    op.create_table(
        "boot_splash_themes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("theme_name", sa.String(64), nullable=False),
        sa.Column("package_name", sa.String(64), nullable=True),
        sa.Column("config_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "login_screen_themes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "branding_profile_id",
            sa.String(36),
            sa.ForeignKey("branding_profiles.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("theme_name", sa.String(64), nullable=False),
        sa.Column("display_manager", sa.String(32), nullable=True),
        sa.Column("config_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    for tbl in (
        "login_screen_themes",
        "boot_splash_themes",
        "wallpaper_sets",
        "motd_templates",
        "os_release_templates",
        "branding_targets",
        "branding_assets",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass

    # Drop added columns from branding_profiles (SQLite: only if they exist)
    existing_cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("branding_profiles")}
    for col_name, _ in reversed(_NEW_COLS):
        if col_name in existing_cols:
            try:
                op.drop_column("branding_profiles", col_name)
            except Exception:
                pass
