"""0033 — Explain / Why Engine (M58)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_explain_trace_kinds

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "explain_trace_kinds" in existing_tables:
        return

    op.create_table(
        "explain_trace_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "explain_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey("builds.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("target_kind", sa.String(32), nullable=False),
        sa.Column("target_key", sa.String(256), nullable=False),
        sa.Column("reason_kind", sa.String(32), nullable=False),
        sa.Column("reason_detail", sa.Text, nullable=False, server_default=""),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    with Session(bind) as session:
        seed_explain_trace_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("explain_traces")
    op.drop_table("explain_trace_kinds")
