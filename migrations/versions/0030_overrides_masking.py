"""0030 — Override / Masking engine (M55)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_override_kinds

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "override_kinds" in existing_tables:
        return

    op.create_table(
        "override_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "override_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("rendered_override_policy", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "name", name="uq_override_profiles_dist_name"),
    )

    op.create_table(
        "override_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("override_profiles.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_key", sa.String(256), nullable=False),
        sa.Column("action", sa.String(32), nullable=False, server_default="set"),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("reason", sa.String(256), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "profile_id", "target_type", "target_key",
            name="uq_override_rules_profile_type_key",
        ),
    )

    with Session(bind) as s:
        seed_override_kinds(s)
        s.commit()


def downgrade() -> None:
    op.drop_table("override_rules")
    op.drop_table("override_profiles")
    op.drop_table("override_kinds")
