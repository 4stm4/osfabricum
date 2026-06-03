"""Build Wizard drafts (M28): build_drafts table.

Revision ID: 0008
Revises: 0007

Explicit, idempotent DDL (matching the convention in 0002/0006/0007).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "build_drafts" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "build_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="new"),
        sa.Column("distribution", sa.String(64), nullable=True),
        sa.Column("profile", sa.String(64), nullable=True),
        sa.Column("board", sa.String(64), nullable=True),
        sa.Column("overrides_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("build_drafts")
