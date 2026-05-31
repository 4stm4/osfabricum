"""Add required_tags_json column to jobs for M5 capability routing.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard: fresh installs run 0001 (create_all) which already includes this
    # column because Job.required_tags_json is now in Base.metadata.
    bind = op.get_bind()
    existing_cols = {c["name"] for c in sa.inspect(bind).get_columns("jobs")}
    if "required_tags_json" in existing_cols:
        return
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("required_tags_json", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("required_tags_json")
