"""Add jobs table for M4 job queue backend.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard: migration 0001 uses create_all which on fresh installs already
    # creates the jobs table (because Job is now in Base.metadata).
    bind = op.get_bind()
    if sa.inspect(bind).has_table("jobs"):
        return
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued", index=True),
        sa.Column("payload_json", sa.JSON, nullable=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("retry_policy", sa.String(32), nullable=False, server_default="fixed"),
        sa.Column("worker_hostname", sa.String(128), nullable=True),
        sa.Column("claimed_at", sa.DateTime, nullable=True),
        sa.Column("lease_ttl_s", sa.Integer, nullable=False, server_default="60"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("jobs")
