"""Profile versioning (M27): profile_versions snapshots.

Revision ID: 0007
Revises: 0006

Explicit, idempotent DDL (matching the convention in 0002/0006): on a fresh
database 0001's create_all already built this table, so the guard skips it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "profile_versions" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "profile_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_profile_versions_pv"),
    )


def downgrade() -> None:
    op.drop_table("profile_versions")
