"""0051 — TinyDesk Reference Distribution (M74)."""

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
    seed_tinydesk_reference,
)

revision = "0051"
down_revision = "0050"
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
        seed_tinydesk_reference(session)
        session.commit()


def downgrade() -> None:
    pass
