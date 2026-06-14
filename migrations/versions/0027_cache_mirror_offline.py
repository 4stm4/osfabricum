"""0027 — Cache / Mirror / Offline designer (M51)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_cache_policy_kinds

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "cache_policy_kinds" in existing_tables:
        return

    op.create_table(
        "cache_policy_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "mirror_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("offline_mode", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("max_cache_size_mb", sa.Integer, nullable=True),
        sa.Column("cache_ttl_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("rendered_mirror_config", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "name", name="uq_mirror_profiles_dist_name"),
    )

    op.create_table(
        "mirror_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("mirror_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("requires_auth", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("auth_token_id", sa.String(128), nullable=True),
        sa.UniqueConstraint("profile_id", "url", name="uq_mirror_endpoints_profile_url"),
    )

    op.create_table(
        "cache_priority_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("mirror_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_pattern", sa.String(256), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_policy", sa.String(32), nullable=False, server_default="prefer"),
        sa.UniqueConstraint("profile_id", "source_pattern", name="uq_cache_rules_profile_pattern"),
    )

    with Session(bind) as s:
        seed_cache_policy_kinds(s)
        s.commit()


def downgrade() -> None:
    op.drop_table("cache_priority_rules")
    op.drop_table("mirror_endpoints")
    op.drop_table("mirror_profiles")
    op.drop_table("cache_policy_kinds")
