"""M37 — Package Feed Publisher: FeedChannel, FeedSignature, FeedPublishJob.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "feed_signatures" in existing:
        return  # fresh install already has tables via create_all

    op.create_table(
        "feed_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feed_id", sa.String(36), sa.ForeignKey("package_feeds.id"), nullable=False),
        sa.Column("distribution", sa.String(64), nullable=True),
        sa.Column("arch", sa.String(32), nullable=True),
        sa.Column("libc", sa.String(32), nullable=True),
        sa.Column("kernel_release", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_feed_channels_feed_id", "feed_channels", ["feed_id"])

    op.create_table(
        "feed_signatures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feed_id", sa.String(36), sa.ForeignKey("package_feeds.id"), nullable=False),
        sa.Column("algorithm", sa.String(16), nullable=False),
        sa.Column("index_hash", sa.String(128), nullable=False),
        sa.Column("entry_count", sa.Integer, nullable=False),
        sa.Column("signed_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_feed_signatures_feed_id", "feed_signatures", ["feed_id"])

    op.create_table(
        "feed_publish_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feed_id", sa.String(36), sa.ForeignKey("package_feeds.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("index_hash", sa.String(128), nullable=True),
        sa.Column("entry_count", sa.Integer, nullable=False),
        sa.Column("triggered_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_feed_publish_jobs_feed_id", "feed_publish_jobs", ["feed_id"])


def downgrade() -> None:
    op.drop_index("ix_feed_publish_jobs_feed_id", "feed_publish_jobs")
    op.drop_table("feed_publish_jobs")
    op.drop_index("ix_feed_signatures_feed_id", "feed_signatures")
    op.drop_table("feed_signatures")
    op.drop_index("ix_feed_channels_feed_id", "feed_channels")
    op.drop_table("feed_channels")
