"""0040 — Size / Footprint Optimizer (M65)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_size_budget_kinds

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "size_budget_kinds" in existing_tables:
        return

    op.create_table(
        "size_budget_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "size_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("budget_kind", sa.String(32), nullable=False),
        sa.Column("budget_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("is_hard_limit", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "size_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey("builds.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("rendered_report", sa.Text, nullable=True),
        sa.Column("summary_json", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    with Session(bind) as session:
        seed_size_budget_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("size_reports")
    op.drop_table("size_budgets")
    op.drop_table("size_budget_kinds")
