"""Database tables. Every change also gets a new migration in framegen/db/migrations/versions."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
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
    # Who sent the request: "user:<id>" for a signed-in user.
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

ID = String(40)
"""Prefixed random IDs such as usr_..., see framegen/ids.py."""

users = Table(
    "users",
    metadata,
    Column("id", ID, primary_key=True),
    # Stored lower-cased, so sign-in ignores case and an address is used once.
    Column("email", String(254), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    Column("language", String(16), nullable=False, server_default="en"),
    Column("password_hash", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", ID, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('personal', 'studio')", name="kind"),
)

memberships = Table(
    "memberships",
    metadata,
    Column("workspace_id", ID, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("role IN ('owner', 'admin', 'member')", name="role"),
    Index("ix_memberships_user_id", "user_id"),
)

sessions = Table(
    "sessions",
    metadata,
    # sha256 of the cookie value: a database leak does not hand out working sessions.
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
    Index("ix_sessions_user_id", "user_id"),
)

invitations = Table(
    "invitations",
    metadata,
    Column("id", ID, primary_key=True),
    Column("workspace_id", ID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("email", String(254), nullable=False),
    Column("role", String(16), nullable=False),
    # sha256 of the token sent to the invitee, as for sessions.
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("invited_by", ID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("role IN ('owner', 'admin', 'member')", name="role"),
    UniqueConstraint("workspace_id", "email", name="uq_invitations_workspace_id_email"),
)

assets = Table(
    "assets",
    metadata,
    Column("id", ID, primary_key=True),
    Column("workspace_id", ID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    # What the file is for: reference, font, stamp or template-source (uploads); piece,
    # render or package (made by FrameGen).
    Column("kind", String(32), nullable=False),
    # pending until the upload is confirmed, then ready. rejected: the upload was not the
    # declared file; its stored object is deleted, and the row is kept so retention can
    # also remove anything uploaded again through the still-valid link.
    Column("status", String(16), nullable=False),
    Column("storage_key", String(200), nullable=False, unique=True),
    Column("filename", String(255), nullable=False),
    Column("content_type", String(100), nullable=False),
    Column("size", BigInteger, nullable=False),
    # sha256 of the content, hex. Storage refuses an upload whose content does not match.
    Column("sha256", String(64), nullable=False),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    Column("created_by", ID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("status IN ('pending', 'ready', 'rejected')", name="status"),
    Index("ix_assets_workspace_id_id", "workspace_id", "id"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", ID, primary_key=True),
    Column("workspace_id", ID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    # What the job does, such as demo; one Procrastinate task per type.
    Column("type", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    # 0 to 1, and a short English note on the current step, for developers.
    Column("progress", Float, nullable=False, server_default="0"),
    Column("step", String(200), nullable=True),
    Column("result", JSONB, nullable=True),
    # A stable code for programs (as in API errors) and an English hint.
    Column("error_code", String(64), nullable=True),
    Column("error_message", String(500), nullable=True),
    Column("created_by", ID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
    CheckConstraint("progress >= 0 AND progress <= 1", name="progress"),
    Index("ix_jobs_workspace_id_id", "workspace_id", "id"),
    # One demo job at a time per workspace, also when requests arrive together.
    Index(
        "uq_jobs_one_active_demo",
        "workspace_id",
        unique=True,
        postgresql_where=text("type = 'demo' AND status IN ('queued', 'running')"),
    ),
)

brand_kits = Table(
    "brand_kits",
    metadata,
    Column("workspace_id", ID, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
    # The kit as the API shows it (framegen.api.brand_kit.BrandKitContent).
    Column("content", JSONB, nullable=False),
    # Each save adds one; a save naming an older version is refused, so none is lost.
    Column("version", Integer, nullable=False),
    Column("updated_by", ID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="version"),
)
