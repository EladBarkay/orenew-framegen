"""Database tables. Every change also gets a new migration in framegen/db/migrations/versions."""

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    # Who sent the request. "anonymous" until accounts exist (T-06).
    Column("scope", String(200), primary_key=True),
    Column("key", String(255), primary_key=True),
    # sha256 of method, path, query and body: the same key must not be reused for another request.
    Column("fingerprint", String(64), nullable=False),
    # Null while the first request is still being handled.
    Column("status_code", Integer, nullable=True),
    Column("response_headers", JSONB, nullable=True),
    Column("response_body", LargeBinary, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
)
