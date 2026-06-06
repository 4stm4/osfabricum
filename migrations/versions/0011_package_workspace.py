"""Package Workspace / Package Manager (M35): taxonomy, cache, locks, feeds.

Revision ID: 0011
Revises: 0010

Explicit, idempotent DDL (matching 0006-0010): on a fresh database 0001's
create_all already built these tables and the new packages.kind/layer columns,
so the guard skips. The fixed package kinds/layers are seeded here (idempotent).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from osfabricum.db.seed_data import PACKAGE_KINDS, PACKAGE_LAYERS

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    fresh = "package_cache_entries" not in set(sa.inspect(bind).get_table_names())

    if fresh:
        op.create_table(
            "package_kinds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(32), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
        )
        op.create_table(
            "package_layers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(32), nullable=False, unique=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("description", sa.Text(), nullable=True),
        )
        op.create_table(
            "package_variants",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("package_id", sa.String(36), sa.ForeignKey("packages.id"), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("feature_hash", sa.String(128), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.UniqueConstraint("package_id", "name", name="uq_package_variant_name"),
        )
        op.create_index("ix_package_variants_package_id", "package_variants", ["package_id"])
        op.create_table(
            "package_variant_features",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "variant_id", sa.String(36), sa.ForeignKey("package_variants.id"), nullable=False
            ),
            sa.Column("feature", sa.String(64), nullable=False),
            sa.Column("value", sa.String(128), nullable=False),
        )
        op.create_index(
            "ix_package_variant_features_variant_id", "package_variant_features", ["variant_id"]
        )
        op.create_table(
            "package_cache_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("cache_key", sa.String(128), nullable=False, unique=True),
            sa.Column("package_name", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("arch", sa.String(32), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("key_fields_json", _JSON, nullable=False),
            sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_package_cache_entries_package_name", "package_cache_entries", ["package_name"]
        )
        op.create_table(
            "package_compatibility",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "cache_entry_id",
                sa.String(36),
                sa.ForeignKey("package_cache_entries.id"),
                nullable=False,
            ),
            sa.Column("package_name", sa.String(64), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("kernel_release", sa.String(64), nullable=True),
            sa.Column("kernel_config_hash", sa.String(128), nullable=True),
            sa.Column("toolchain_hash", sa.String(128), nullable=True),
            sa.Column("abi_hash", sa.String(128), nullable=True),
        )
        op.create_index(
            "ix_package_compatibility_cache_entry_id", "package_compatibility", ["cache_entry_id"]
        )
        op.create_index(
            "ix_package_compatibility_package_name", "package_compatibility", ["package_name"]
        )
        op.create_table(
            "package_locks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("package_name", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("cache_key", sa.String(128), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("package_name", "version", name="uq_package_lock"),
        )
        op.create_table(
            "package_feeds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(64), nullable=False, unique=True),
            sa.Column("channel", sa.String(32), nullable=False, server_default="stable"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_table(
            "package_feed_indexes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("feed_id", sa.String(36), sa.ForeignKey("package_feeds.id"), nullable=False),
            sa.Column("package_name", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("cache_key", sa.String(128), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_package_feed_indexes_feed_id", "package_feed_indexes", ["feed_id"])
        op.create_table(
            "package_promotions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("package_name", sa.String(64), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("from_channel", sa.String(32), nullable=True),
            sa.Column("to_channel", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_package_promotions_package_name", "package_promotions", ["package_name"]
        )
        op.create_table(
            "package_install_plans",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("set_id", sa.String(36), sa.ForeignKey("package_sets.id"), nullable=True),
            sa.Column("profile_id", sa.String(36), nullable=True),
            sa.Column("plan_json", _JSON, nullable=False),
            sa.Column("plan_hash", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

        # Extend packages with taxonomy columns (additive, nullable).
        existing = {c["name"] for c in sa.inspect(bind).get_columns("packages")}
        if "kind" not in existing:
            op.add_column("packages", sa.Column("kind", sa.String(32), nullable=True))
        if "layer" not in existing:
            op.add_column("packages", sa.Column("layer", sa.String(32), nullable=True))

    # Seed the fixed kinds/layers (idempotent: only when empty).
    kinds = sa.table("package_kinds", sa.column("id"), sa.column("name"), sa.column("description"))
    if not bind.execute(sa.select(sa.func.count()).select_from(kinds)).scalar():
        op.bulk_insert(
            kinds, [{"id": str(uuid4()), "name": n, "description": d} for n, d in PACKAGE_KINDS]
        )
    layers = sa.table(
        "package_layers",
        sa.column("id"),
        sa.column("name"),
        sa.column("position"),
        sa.column("description"),
    )
    if not bind.execute(sa.select(sa.func.count()).select_from(layers)).scalar():
        op.bulk_insert(
            layers,
            [
                {"id": str(uuid4()), "name": n, "position": p, "description": d}
                for n, p, d in PACKAGE_LAYERS
            ],
        )


def downgrade() -> None:
    op.drop_column("packages", "layer")
    op.drop_column("packages", "kind")
    for tbl in (
        "package_install_plans",
        "package_promotions",
        "package_feed_indexes",
        "package_feeds",
        "package_locks",
        "package_compatibility",
        "package_cache_entries",
        "package_variant_features",
        "package_variants",
        "package_layers",
        "package_kinds",
    ):
        op.drop_table(tbl)
