"""At most one queued or running demo job per workspace (T-08b review).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_one_active_demo",
        "jobs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("type = 'demo' AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_one_active_demo", table_name="jobs")
