"""Universal OS Builder Model (M25): distribution classes + universal entities.

Revision ID: 0006
Revises: 0005

Explicit DDL (``op.create_table`` / ``op.add_column``) for every new table and
column — the new tables are owned by this migration, not by the
``metadata.create_all`` baseline in ``0001`` (closes audit gap G-23 for new
tables). Every step is guarded for idempotency, matching the established
convention in ``0002`` ("fresh install via create_all or previous run"):

* on a fresh database ``0001``'s ``create_all`` has already built the current
  model schema (including these tables/columns), so the guards skip creation
  and only the fixed-enumeration seed runs;
* on a database migrated before M25 the tables/columns do not exist yet, so the
  explicit DDL creates them.

Either way the result matches the ORM models — verified by
``tests/unit/test_migrations.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from osfabricum.db.seed_data import BOOT_SCHEMES, DISTRIBUTION_CLASSES

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# New nullable FK columns added to ``profiles`` (col_name -> referenced).
_PROFILE_FKS: list[tuple[str, str]] = [
    ("class_id", "distribution_classes.id"),
    ("board_id", "boards.id"),
    ("kernel_id", "kernels.id"),
    ("toolchain_id", "toolchains.id"),
    ("package_set_id", "package_sets.id"),
    ("boot_scheme_id", "boot_schemes.id"),
    ("image_recipe_id", "image_recipes.id"),
    ("branding_profile_id", "branding_profiles.id"),
    ("graphical_profile_id", "graphical_profiles.id"),
    ("network_profile_id", "network_profiles.id"),
    ("security_profile_id", "security_profiles.id"),
    ("update_strategy_id", "update_strategies.id"),
    ("validation_profile_id", "validation_profiles.id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables: set[str] = set(insp.get_table_names())

    def cols_of(table: str) -> set[str]:
        if table not in existing_tables:
            return set()
        return {c["name"] for c in insp.get_columns(table)}

    def create(table: str, *items: object) -> None:
        if table not in existing_tables:
            op.create_table(table, *items)

    def add_col(table: str, column: sa.Column) -> None:
        if column.name not in cols_of(table):
            op.add_column(table, column)

    def named_entity(table: str, *extra: sa.Column) -> None:
        create(
            table,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column(
                "distribution_id", sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
            ),
            *extra,
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.UniqueConstraint("distribution_id", "name", name=f"uq_{table}_dist_name"),
        )

    # --- lookup / enumeration tables ---
    create(
        "distribution_classes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    create(
        "boot_schemes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )

    # --- package grouping ---
    create(
        "package_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("distribution_id", "name", name="uq_package_groups_dist_name"),
    )
    create(
        "package_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36), sa.ForeignKey("distributions.id"), nullable=True
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("distribution_id", "name", name="uq_package_sets_dist_name"),
    )
    create(
        "package_group_members",
        sa.Column("group_id", sa.String(36), sa.ForeignKey("package_groups.id"), primary_key=True),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("packages.id"), primary_key=True),
        sa.Column("version_constraint", sa.String(64), nullable=True),
    )
    create(
        "package_set_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("set_id", sa.String(36), sa.ForeignKey("package_sets.id"), nullable=False),
        sa.Column("member_kind", sa.String(16), nullable=False),
        sa.Column("group_id", sa.String(36), sa.ForeignKey("package_groups.id"), nullable=True),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("packages.id"), nullable=True),
    )

    # --- universal profile-like entities (rich fields land per designer) ---
    named_entity(
        "image_recipes",
        sa.Column("output_format", sa.String(32), nullable=False, server_default="raw"),
    )
    named_entity("branding_profiles")
    named_entity(
        "graphical_profiles",
        sa.Column("mode", sa.String(32), nullable=False, server_default="no-gui"),
    )
    named_entity("network_profiles")
    named_entity("security_profiles")
    named_entity(
        "update_strategies",
        sa.Column("strategy", sa.String(32), nullable=False, server_default="full-image"),
    )
    named_entity("validation_profiles")

    # --- reference columns on existing tables ---
    # Added as plain String(36) columns: SQLite cannot ``ALTER TABLE ADD COLUMN``
    # with a FK constraint (it has no ALTER-ADD-CONSTRAINT), and the project
    # already uses unconstrained id columns (e.g. ``artifacts.producer_build_id``).
    # The referential relationship is declared on the ORM models (see
    # ``_PROFILE_FKS`` for the intended targets), so it applies on fresh
    # metadata-built databases and drives relationship navigation.
    add_col("distributions", sa.Column("class_id", sa.String(36), nullable=True))
    for col, _target in _PROFILE_FKS:
        add_col("profiles", sa.Column(col, sa.String(36), nullable=True))

    # --- seed fixed enumerations (idempotent: only when empty) ---
    dc = sa.table(
        "distribution_classes", sa.column("id"), sa.column("name"), sa.column("description")
    )
    if not bind.execute(sa.select(sa.func.count()).select_from(dc)).scalar():
        op.bulk_insert(
            dc, [{"id": str(uuid4()), "name": n, "description": d} for n, d in DISTRIBUTION_CLASSES]
        )
    bs = sa.table("boot_schemes", sa.column("id"), sa.column("name"), sa.column("description"))
    if not bind.execute(sa.select(sa.func.count()).select_from(bs)).scalar():
        op.bulk_insert(
            bs, [{"id": str(uuid4()), "name": n, "description": d} for n, d in BOOT_SCHEMES]
        )


def downgrade() -> None:
    # Batch mode (copy-and-move) so the column drops work on SQLite even when
    # the table was created by ``metadata.create_all`` with FK constraints.
    with op.batch_alter_table("profiles") as batch_op:
        for col, _ in reversed(_PROFILE_FKS):
            batch_op.drop_column(col)
    with op.batch_alter_table("distributions") as batch_op:
        batch_op.drop_column("class_id")
    for table in (
        "validation_profiles",
        "update_strategies",
        "security_profiles",
        "network_profiles",
        "graphical_profiles",
        "branding_profiles",
        "image_recipes",
        "package_set_members",
        "package_group_members",
        "package_sets",
        "package_groups",
        "boot_schemes",
        "distribution_classes",
    ):
        op.drop_table(table)
