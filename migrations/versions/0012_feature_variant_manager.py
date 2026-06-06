"""Package Feature / Variant Manager (M36): feature options, values, variants.

Revision ID: 0012
Revises: 0011

Explicit, idempotent DDL (matching 0006-0011): on a fresh database 0001's
create_all already built these tables, so the guard skips.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    if "package_feature_options" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "package_feature_options",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("default_value", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("package_id", "name", name="uq_package_feature_option"),
    )
    op.create_index(
        "ix_package_feature_options_package_id", "package_feature_options", ["package_id"]
    )

    op.create_table(
        "package_feature_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "option_id",
            sa.String(36),
            sa.ForeignKey("package_feature_options.id"),
            nullable=False,
        ),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("implied_deps_json", _JSON, nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_package_feature_values_option_id", "package_feature_values", ["option_id"])

    op.create_table(
        "package_build_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("feature_hash", sa.String(128), nullable=False),
        sa.Column("arch", sa.String(32), nullable=True),
        sa.Column("resolved_json", _JSON, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("package_id", "feature_hash", "arch", name="uq_package_build_variant"),
    )
    op.create_index(
        "ix_package_build_variants_package_id", "package_build_variants", ["package_id"]
    )

    op.create_table(
        "package_variant_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_variant_id",
            sa.String(36),
            sa.ForeignKey("package_build_variants.id"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("arch", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_package_variant_artifacts_build_variant_id",
        "package_variant_artifacts",
        ["build_variant_id"],
    )


def downgrade() -> None:
    for tbl in (
        "package_variant_artifacts",
        "package_build_variants",
        "package_feature_values",
        "package_feature_options",
    ):
        op.drop_table(tbl)
