"""0039 — Build Analysis Dashboard (M64)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "build_analyses" in existing_tables:
        return

    op.create_table(
        "build_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey("builds.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("analysis_kind", sa.String(32), nullable=False, server_default="time"),
        sa.Column("rendered_report", sa.Text, nullable=True),
        sa.Column("summary_json", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("build_analyses")
