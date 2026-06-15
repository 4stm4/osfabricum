"""0031 — Patch Queue / Source Patch Manager (M56)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_patch_target_kinds

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "patch_target_kinds" in existing_tables:
        return

    op.create_table(
        "patch_target_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "patch_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("target_kind", sa.String(32), nullable=False, server_default="kernel"),
        sa.Column("rendered_patch_manifest", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "name", name="uq_patch_sets_dist_name"),
    )

    op.create_table(
        "patches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "patch_set_id", sa.String(36),
            sa.ForeignKey("patch_sets.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("sequence_num", sa.Integer, nullable=False, server_default="0"),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("patch_content", sa.Text, nullable=False, server_default=""),
        sa.Column("patch_format", sa.String(32), nullable=False, server_default="diff"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.UniqueConstraint("patch_set_id", "sequence_num", name="uq_patches_set_seq"),
    )

    op.create_table(
        "patch_application_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "patch_set_id", sa.String(36),
            sa.ForeignKey("patch_sets.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("applied_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_at_sequence", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    with Session(bind) as session:
        seed_patch_target_kinds(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("patch_application_results")
    op.drop_table("patches")
    op.drop_table("patch_sets")
    op.drop_table("patch_target_kinds")
