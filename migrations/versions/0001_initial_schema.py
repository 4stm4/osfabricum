"""Initial schema — all tables from ROADMAP section 4.

Revision ID: 0001
Revises:
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Ensure all ORM models are registered before create_all() is called.
import osfabricum.db.models  # noqa: F401
from osfabricum.db.base import Base

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
