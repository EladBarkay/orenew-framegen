"""Idempotency keys (T-05).

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_headers", postgresql.JSONB(), nullable=True),
        sa.Column("response_body", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope", "key", name=op.f("pk_idempotency_keys")),
    )
    op.create_index(op.f("ix_idempotency_keys_expires_at"), "idempotency_keys", ["expires_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_idempotency_keys_expires_at"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
