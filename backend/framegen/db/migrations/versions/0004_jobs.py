"""Background jobs: Procrastinate's queue and FrameGen's jobs table (T-08a).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Procrastinate's own schema, from the pinned version in pyproject.toml. A later
# Procrastinate upgrade adds a migration that applies its migration files in between.
_DROP_PROCRASTINATE = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers,
    procrastinate_jobs, procrastinate_workers CASCADE;
DO $$
DECLARE f record;
BEGIN
    FOR f IN SELECT oid::regprocedure AS signature FROM pg_proc
             WHERE proname LIKE 'procrastinate\\_%' LOOP
        EXECUTE 'DROP FUNCTION ' || f.signature || ' CASCADE';
    END LOOP;
END $$;
DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, procrastinate_job_event_type,
    procrastinate_job_status CASCADE;
"""


def upgrade() -> None:
    op.execute(SchemaManager.get_schema())
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("step", sa.String(length=200), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name=op.f("ck_jobs_progress")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name=op.f("ck_jobs_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_jobs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_jobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_workspace_id_id", "jobs", ["workspace_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_workspace_id_id", table_name="jobs")
    op.drop_table("jobs")
    op.execute(_DROP_PROCRASTINATE)
