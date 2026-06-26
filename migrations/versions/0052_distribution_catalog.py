"""0052 — Distribution catalog YAML loader (M75).

Seeds all distributions from catalog/seed/distributions/*.yaml.
Each YAML file defines one distribution: packages, groups, sets, profiles.
Adding a new distribution now requires only a new YAML file.
"""

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
    seed_distribution_catalog,
)

revision = "0052"
down_revision = "0051"
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
        seed_distribution_catalog(session)
        session.commit()


def downgrade() -> None:
    pass
