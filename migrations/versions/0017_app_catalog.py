"""M41 — Application Catalog Designer.

Creates: app_categories, app_catalog_profiles, catalog_apps,
         app_groups, app_group_members, default_app_roles.
Seeds 11 app categories.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "app_categories" not in existing_tables

    if not fresh:
        return  # tables already created by create_all (fresh install)

    op.create_table(
        "app_categories",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "app_catalog_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rendered_app_list", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_app_catalog_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_app_catalog_profiles_distribution_id",
        "app_catalog_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "catalog_apps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_profile_id",
            sa.String(36),
            sa.ForeignKey("app_catalog_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category_name", sa.String(64), nullable=False, default="utilities"),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("version_constraint", sa.String(64), nullable=True),
        sa.Column("icon_name", sa.String(128), nullable=True),
        sa.Column("is_default_install", sa.Boolean, nullable=False, default=True),
        sa.Column("is_optional", sa.Boolean, nullable=False, default=False),
        sa.Column("tags", sa.JSON, nullable=False, default=list),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "catalog_profile_id", "name", name="uq_catalog_apps_profile_name"
        ),
    )
    op.create_index(
        "ix_catalog_apps_profile_id", "catalog_apps", ["catalog_profile_id"]
    )

    op.create_table(
        "app_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_profile_id",
            sa.String(36),
            sa.ForeignKey("app_catalog_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "catalog_profile_id", "name", name="uq_app_groups_profile_name"
        ),
    )
    op.create_index(
        "ix_app_groups_profile_id", "app_groups", ["catalog_profile_id"]
    )

    op.create_table(
        "app_group_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("app_groups.id"),
            nullable=False,
        ),
        sa.Column(
            "catalog_app_id",
            sa.String(36),
            sa.ForeignKey("catalog_apps.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False, default=0),
        sa.UniqueConstraint(
            "group_id", "catalog_app_id", name="uq_app_group_members_group_app"
        ),
    )
    op.create_index(
        "ix_app_group_members_group_id", "app_group_members", ["group_id"]
    )

    op.create_table(
        "default_app_roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_profile_id",
            sa.String(36),
            sa.ForeignKey("app_catalog_profiles.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("app_name", sa.String(64), nullable=False),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "catalog_profile_id", "role", name="uq_default_app_roles_profile_role"
        ),
    )
    op.create_index(
        "ix_default_app_roles_profile_id",
        "default_app_roles",
        ["catalog_profile_id"],
    )

    # Seed app categories
    from osfabricum.db.seed_data import APP_CATEGORIES  # noqa: PLC0415

    cat_table = sa.table(
        "app_categories",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("icon", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing_cats = {
        row[0]
        for row in bind.execute(sa.text("SELECT name FROM app_categories")).fetchall()
    }
    for name, description, icon, display_order in APP_CATEGORIES:
        if name in existing_cats:
            continue
        bind.execute(
            cat_table.insert().values(
                name=name,
                description=description,
                icon=icon,
                display_order=display_order,
            )
        )


def downgrade() -> None:
    for tbl in (
        "default_app_roles",
        "app_group_members",
        "app_groups",
        "catalog_apps",
        "app_catalog_profiles",
        "app_categories",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
