"""0029 — OS Composition Layers designer (M54)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_layer_kinds

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "layer_kinds" in existing_tables:
        return

    op.create_table(
        "layer_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "layer_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("base_layer", sa.String(32), nullable=False, server_default="base"),
        sa.Column("rendered_manifest", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "name", name="uq_layer_profiles_dist_name"),
    )

    op.create_table(
        "layer_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("layer_profiles.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("layer_kind", sa.String(32), nullable=False, server_default="extension"),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("sha256_hint", sa.String(71), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("description", sa.String(256), nullable=False, server_default=""),
        sa.UniqueConstraint("profile_id", "name", name="uq_layer_entries_profile_name"),
    )

    with Session(bind) as s:
        seed_layer_kinds(s)
        s.commit()


def downgrade() -> None:
    op.drop_table("layer_entries")
    op.drop_table("layer_profiles")
    op.drop_table("layer_kinds")
