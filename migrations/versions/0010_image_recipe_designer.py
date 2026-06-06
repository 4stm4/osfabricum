"""Filesystem / Image Recipe Designer (M34): recipes, outputs, filesystems, sizing.

Revision ID: 0010
Revises: 0009

Explicit, idempotent DDL (matching 0006-0009): on a fresh database 0001's
create_all already built these tables and the new image_recipes columns, so the
guard skips. On an incrementally-upgraded database the tables/columns are added.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    if "image_outputs" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "filesystem_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("fs_type", sa.String(16), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("mount_point", sa.String(128), nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("compression", sa.String(16), nullable=True),
        sa.Column("options_json", _JSON, nullable=True),
    )

    op.create_table(
        "size_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("free_space_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_free_mb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("align_mb", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("reserve_mb", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("grow_to_fit", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "partition_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "layout_id", sa.String(36), sa.ForeignKey("partition_layouts.id"), nullable=False
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column(
            "filesystem_id", sa.String(36), sa.ForeignKey("filesystem_profiles.id"), nullable=True
        ),
        sa.Column("size_mb", sa.Integer(), nullable=True),
        sa.Column("grow", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flags_json", _JSON, nullable=True),
        sa.UniqueConstraint("layout_id", "name", name="uq_partition_entry_name"),
    )
    op.create_index("ix_partition_entries_layout_id", "partition_entries", ["layout_id"])

    op.create_table(
        "image_outputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False),
        sa.Column("output_format", sa.String(24), nullable=False),
        sa.Column("compression", sa.String(16), nullable=True),
        sa.Column("filename_template", sa.String(255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("recipe_id", "output_format", name="uq_image_output_format"),
    )
    op.create_index("ix_image_outputs_recipe_id", "image_outputs", ["recipe_id"])

    op.create_table(
        "mount_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("fstype", sa.String(24), nullable=False),
        sa.Column("options", sa.String(255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_mount_policies_recipe_id", "mount_policies", ["recipe_id"])

    op.create_table(
        "overlay_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), sa.ForeignKey("image_recipes.id"), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("lower_dir", sa.String(255), nullable=False),
        sa.Column("upper_dir", sa.String(255), nullable=False),
        sa.Column("work_dir", sa.String(255), nullable=False),
        sa.Column("persistent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_overlay_policies_recipe_id", "overlay_policies", ["recipe_id"])

    # Extend image_recipes into the recipe hub (additive, nullable columns).
    existing = {c["name"] for c in sa.inspect(bind).get_columns("image_recipes")}
    for name, col in (
        ("description", sa.Column("description", sa.Text(), nullable=True)),
        ("partition_layout_id", sa.Column("partition_layout_id", sa.String(36), nullable=True)),
        ("size_policy_id", sa.Column("size_policy_id", sa.String(36), nullable=True)),
        ("root_filesystem_id", sa.Column("root_filesystem_id", sa.String(36), nullable=True)),
    ):
        if name not in existing:
            op.add_column("image_recipes", col)


def downgrade() -> None:
    for col in ("root_filesystem_id", "size_policy_id", "partition_layout_id", "description"):
        op.drop_column("image_recipes", col)
    for tbl in (
        "overlay_policies",
        "mount_policies",
        "image_outputs",
        "partition_entries",
        "size_policies",
        "filesystem_profiles",
    ):
        op.drop_table(tbl)
