"""Add input_hash column to artifacts table (M13).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("input_hash", sa.String(128), nullable=True))
    op.create_index("ix_artifacts_input_hash", "artifacts", ["input_hash"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_input_hash", table_name="artifacts")
    op.drop_column("artifacts", "input_hash")
