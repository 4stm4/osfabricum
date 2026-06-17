"""0042 — Distributed Build Farm / Worker Pools (M67)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "worker_pools" in existing_tables:
        return

    op.create_table(
        "worker_pools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("pool_kind", sa.String(32), nullable=False, server_default="local"),
        sa.Column("max_parallelism", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "worker_pool_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "worker_pool_id", sa.String(36),
            sa.ForeignKey("worker_pools.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "worker_id", sa.String(36),
            sa.ForeignKey("workers.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("joined_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "job_affinities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "pool_id", sa.String(36),
            sa.ForeignKey("worker_pools.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("job_kind", sa.String(64), nullable=False),
        sa.Column("affinity_weight", sa.Integer, nullable=False, server_default="1"),
    )

    op.create_table(
        "pool_quotas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "pool_id", sa.String(36),
            sa.ForeignKey("worker_pools.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("limit_value", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("period_seconds", sa.Integer, nullable=False, server_default="3600"),
    )


def downgrade() -> None:
    op.drop_table("pool_quotas")
    op.drop_table("job_affinities")
    op.drop_table("worker_pool_members")
    op.drop_table("worker_pools")
