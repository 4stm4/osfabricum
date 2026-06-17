"""0038 — Importers from Competitors / Existing Systems (M63)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_import_kinds

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "import_kinds" in existing_tables:
        return

    op.create_table(
        "import_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_kind", sa.String(32), nullable=False),
        sa.Column("source_data", sa.Text, nullable=True),
        sa.Column("source_filename", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "import_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "import_job_id", sa.String(36),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("mapped_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("report_text", sa.Text, nullable=True),
        sa.Column("draft_profile_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    with Session(bind) as session:
        seed_import_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("import_reports")
    op.drop_table("import_jobs")
    op.drop_table("import_kinds")
