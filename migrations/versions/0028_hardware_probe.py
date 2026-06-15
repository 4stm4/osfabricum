"""0028 — Hardware probe import designer (M53)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_probe_source_kinds

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "probe_source_kinds" in existing_tables:
        return

    op.create_table(
        "probe_source_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "hardware_probes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "board_id", sa.String(36),
            sa.ForeignKey("boards.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("probe_source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("raw_probe_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("cpu_arch", sa.String(32), nullable=True),
        sa.Column("cpu_model", sa.String(128), nullable=True),
        sa.Column("mem_mb", sa.Integer, nullable=True),
        sa.Column("rendered_board_hints", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("probed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    with Session(bind) as s:
        seed_probe_source_kinds(s)
        s.commit()


def downgrade() -> None:
    op.drop_table("hardware_probes")
    op.drop_table("probe_source_kinds")
