"""0045 — TinyWifi Reference Distribution (M71)."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import (
    seed_architectures_from_yaml,
    seed_boards_from_yaml,
    seed_toolchains_from_yaml,
    seed_kernels_from_yaml,
    seed_distributions_from_yaml,
    seed_distribution_classes,
    seed_tinywifi_reference,
)

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    with Session(bind=bind) as session:
        seed_distribution_classes(session)
        seed_architectures_from_yaml(session)
        seed_boards_from_yaml(session)
        seed_toolchains_from_yaml(session)
        seed_kernels_from_yaml(session)
        seed_distributions_from_yaml(session)
        seed_tinywifi_reference(session)
        session.commit()


def downgrade() -> None:
    pass
