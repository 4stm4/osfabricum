"""0046 — NetOS Reference Distribution (M72)."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_netos_reference

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    with Session(bind=bind) as session:
        seed_netos_reference(session)
        session.commit()


def downgrade() -> None:
    pass
