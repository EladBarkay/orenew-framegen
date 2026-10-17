"""Brand kits: a workspace's stamps, fonts, colours and stamp placement (T-15b).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_kits",
        sa.Column("workspace_id", sa.String(40), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_brand_kits_version")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_brand_kits_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_brand_kits_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_brand_kits")),
    )


def downgrade() -> None:
    op.drop_table("brand_kits")
