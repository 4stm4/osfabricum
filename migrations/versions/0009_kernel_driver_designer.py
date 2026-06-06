"""Kernel / Driver Designer (M33): Kconfig index + driver bundles + ext modules.

Revision ID: 0009
Revises: 0fc79d3e6064

Explicit, idempotent DDL (matching 0006-0008): on a fresh database 0001's
create_all already built these tables, so the guard skips creation.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0fc79d3e6064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON()


def upgrade() -> None:
    if "kernel_kconfig_indexes" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "kernel_kconfig_indexes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kernel_id", sa.String(36), sa.ForeignKey("kernels.id"), nullable=False),
        sa.Column("arch", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kernel_id", "arch", "source_ref", name="uq_kconfig_index"),
    )
    op.create_index("ix_kernel_kconfig_indexes_kernel_id", "kernel_kconfig_indexes", ["kernel_id"])

    op.create_table(
        "kernel_option_symbols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "index_id", sa.String(36), sa.ForeignKey("kernel_kconfig_indexes.id"), nullable=False
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("help", sa.Text(), nullable=True),
        sa.Column("default_value", sa.String(64), nullable=True),
        sa.Column("depends_on", sa.Text(), nullable=True),
        sa.Column("choice_group", sa.String(128), nullable=True),
        sa.Column("metadata_json", _JSON, nullable=True),
        sa.UniqueConstraint("index_id", "name", name="uq_kconfig_symbol"),
    )
    op.create_index("ix_kernel_option_symbols_index_id", "kernel_option_symbols", ["index_id"])
    op.create_index("ix_kernel_option_symbols_name", "kernel_option_symbols", ["name"])

    op.create_table(
        "kernel_option_dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "symbol_id", sa.String(36), sa.ForeignKey("kernel_option_symbols.id"), nullable=False
        ),
        sa.Column("dep_kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_kernel_option_dependencies_symbol_id", "kernel_option_dependencies", ["symbol_id"]
    )

    op.create_table(
        "kernel_config_fragments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kernel_id", sa.String(36), sa.ForeignKey("kernels.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kernel_id", "name", name="uq_kconfig_fragment"),
    )
    op.create_table(
        "kernel_config_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "fragment_id", sa.String(36), sa.ForeignKey("kernel_config_fragments.id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(128), nullable=False),
        sa.Column("value", sa.String(64), nullable=False),
    )
    op.create_index("ix_kernel_config_values_fragment_id", "kernel_config_values", ["fragment_id"])

    op.create_table(
        "kernel_config_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kernel_id", sa.String(36), sa.ForeignKey("kernels.id"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kernel_id", "name", name="uq_kconfig_preset"),
    )

    op.create_table(
        "driver_bundles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kernel_id", sa.String(36), sa.ForeignKey("kernels.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for tbl, cols in (
        ("driver_bundle_kernel_options", [("symbol", sa.String(128)), ("value", sa.String(8))]),
        ("driver_bundle_modules", [("module_name", sa.String(128))]),
        ("driver_bundle_firmware", [("filename", sa.String(255))]),
        ("driver_bundle_dt_overlays", [("overlay_name", sa.String(255))]),
    ):
        extra = [sa.Column(n, t, nullable=False) for n, t in cols]
        op.create_table(
            tbl,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "bundle_id", sa.String(36), sa.ForeignKey("driver_bundles.id"), nullable=False
            ),
            *extra,
        )
        op.create_index(f"ix_{tbl}_bundle_id", tbl, ["bundle_id"])

    op.create_table(
        "external_kernel_modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.String(128), nullable=True),
        sa.Column("metadata_json", _JSON, nullable=True),
    )
    op.create_table(
        "external_kernel_module_recipes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "module_id", sa.String(36), sa.ForeignKey("external_kernel_modules.id"), nullable=False
        ),
        sa.Column("kernel_id", sa.String(36), sa.ForeignKey("kernels.id"), nullable=False),
        sa.Column("build_system", sa.String(32), nullable=False, server_default="kbuild"),
        sa.Column("steps_json", _JSON, nullable=True),
    )
    op.create_index(
        "ix_external_kernel_module_recipes_module_id",
        "external_kernel_module_recipes",
        ["module_id"],
    )


def downgrade() -> None:
    for tbl in (
        "external_kernel_module_recipes",
        "external_kernel_modules",
        "driver_bundle_dt_overlays",
        "driver_bundle_firmware",
        "driver_bundle_modules",
        "driver_bundle_kernel_options",
        "driver_bundles",
        "kernel_config_presets",
        "kernel_config_values",
        "kernel_config_fragments",
        "kernel_option_dependencies",
        "kernel_option_symbols",
        "kernel_kconfig_indexes",
    ):
        op.drop_table(tbl)
