"""0035 — System Generations / Rollback Designer (M60)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_rollback_kinds

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "rollback_kinds" in existing_tables:
        return

    op.create_table(
        "rollback_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "generations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("release_id", sa.String(36), nullable=True),
        sa.Column("generation_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("rendered_generation_manifest", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "generation_number", name="uq_generations_dist_num"
        ),
    )

    op.create_table(
        "generation_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "generation_id", sa.String(36),
            sa.ForeignKey("generations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "artifact_id", sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("artifact_role", sa.String(32), nullable=False, server_default="image"),
        sa.Column("artifact_uri", sa.String(512), nullable=True),
        sa.UniqueConstraint(
            "generation_id", "artifact_role", name="uq_gen_artifacts_gen_role"
        ),
    )

    op.create_table(
        "rollback_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "generation_id", sa.String(36),
            sa.ForeignKey("generations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("target_generation_number", sa.Integer, nullable=False),
        sa.Column("rollback_kind", sa.String(32), nullable=False, server_default="full"),
        sa.Column("rendered_rollback_plan", sa.Text, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "generation_id", "target_generation_number",
            name="uq_rollback_targets_gen_tgt",
        ),
    )

    with Session(bind) as session:
        seed_rollback_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("rollback_targets")
    op.drop_table("generation_artifacts")
    op.drop_table("generations")
    op.drop_table("rollback_kinds")
