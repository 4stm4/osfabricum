"""Add metadata_json column to kernels table (M10).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard: already present (fresh install via create_all or previous run).
    bind = op.get_bind()
    if "metadata_json" in {c["name"] for c in sa.inspect(bind).get_columns("kernels")}:
        return
    op.add_column("kernels", sa.Column("metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("kernels", "metadata_json")
