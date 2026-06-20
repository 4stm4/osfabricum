"""0048 — create pyjobkit job_tasks table.

pyjobkit ships its own alembic config but uses the same alembic_version
table, which conflicts with our revision chain. We create job_tasks here
so a single ``alembic upgrade head`` is the only startup command needed.
"""

from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("idempotency_key", sa.Text, unique=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("leased_by", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("timeout_s", sa.Integer),
        sa.CheckConstraint(
            "status IN ('queued','running','success','failed','cancelled','timeout')",
            name="job_status_chk",
        ),
        if_not_exists=True,
    )
    op.create_index(
        "idx_jobs_status_scheduled",
        "job_tasks",
        ["status", "scheduled_for", "priority"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_jobs_leased",
        "job_tasks",
        ["lease_until", "leased_by"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_leased", table_name="job_tasks")
    op.drop_index("idx_jobs_status_scheduled", table_name="job_tasks")
    op.drop_table("job_tasks")
