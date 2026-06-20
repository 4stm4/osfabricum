"""0047 — Ocultum Reference Distribution (M73)."""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_ocultum_reference

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    with Session(bind=bind) as session:
        seed_ocultum_reference(session)
        session.commit()


def downgrade() -> None:
    pass
