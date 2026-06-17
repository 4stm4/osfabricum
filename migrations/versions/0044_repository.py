"""0044 — Public Artifact Repository / Release Publishing (M69)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_release_channels

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "release_channels" in existing_tables:
        return

    op.create_table(
        "release_channels",
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("repo_kind", sa.String(32), nullable=False, server_default="image"),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("sign_key_id", sa.String(128), nullable=True),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "repository_indexes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id", sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("rendered_index", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("indexed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "published_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("rendered_release_manifest", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "release_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "release_id", sa.String(36),
            sa.ForeignKey("published_releases.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "artifact_id", sa.String(36),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("artifact_role", sa.String(32), nullable=False, server_default="image"),
        sa.Column("artifact_uri", sa.String(512), nullable=True),
        sa.UniqueConstraint(
            "release_id", "artifact_role", name="uq_release_artifacts_rel_role"
        ),
    )

    with Session(bind) as session:
        seed_release_channels(session)
        session.commit()


def downgrade() -> None:
    op.drop_table("release_artifacts")
    op.drop_table("published_releases")
    op.drop_table("repository_indexes")
    op.drop_table("repositories")
    op.drop_table("release_channels")
