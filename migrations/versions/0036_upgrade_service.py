"""0036 — Attended Upgrade / Rebuild Service (M61)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "upgrade_requests" in existing_tables:
        return

    op.create_table(
        "upgrade_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "current_generation_id", sa.String(36),
            sa.ForeignKey("generations.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("target_channel", sa.String(64), nullable=False, server_default="stable"),
        sa.Column("target_version", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
    )

    op.create_table(
        "upgrade_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "upgrade_id", sa.String(36),
            sa.ForeignKey("upgrade_requests.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("new_generation_id", sa.String(36), nullable=True),
        sa.Column(
            "artifact_id", sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("diff_report_id", sa.String(36), nullable=True),
        sa.Column("rollback_plan", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("upgrade_results")
    op.drop_table("upgrade_requests")
