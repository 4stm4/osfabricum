"""0032 — Dependency Graph Viewer (M57)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_graph_kinds

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "graph_kinds" in existing_tables:
        return

    op.create_table(
        "graph_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "graph_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("root_node", sa.String(256), nullable=True),
        sa.Column("rendered_graph_json", sa.Text, nullable=True),
        sa.Column("node_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    with Session(bind) as session:
        seed_graph_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("graph_snapshots")
    op.drop_table("graph_kinds")
