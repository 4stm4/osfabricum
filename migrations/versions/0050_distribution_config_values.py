"""0050 — distribution_config_values table.

Stores per-distribution key-value config entries (WiFi SSID/password, DHCP
pool, etc.) that are rendered into package config files at rootfs.compose
time, overriding defaults shipped inside .ofpkg archives.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distribution_config_values",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "key", name="uq_dist_config_values_dist_key"),
    )
    op.create_index(
        "ix_dist_config_values_distribution_id",
        "distribution_config_values",
        ["distribution_id"],
    )

    # Seed default config values and service profile for tinywifi (idempotent)
    from osfabricum.db.seed_data import (  # noqa: PLC0415
        _seed_tinywifi_config_values,
        _seed_tinywifi_service_profile,
    )
    bind = op.get_bind()
    with Session(bind=bind) as session:
        dist = session.execute(
            sa.text("SELECT id FROM distributions WHERE name = 'tinywifi'")
        ).fetchone()
        if dist is not None:
            _seed_tinywifi_config_values(session, dist[0])
            _seed_tinywifi_service_profile(session, dist[0])
            session.commit()


def downgrade() -> None:
    op.drop_index("ix_dist_config_values_distribution_id", table_name="distribution_config_values")
    op.drop_table("distribution_config_values")
