"""Alembic environment: runs migrations against the database from FRAMEGEN_* settings."""

from alembic import context
from sqlalchemy import Connection

from framegen.db.engine import sync_engine
from framegen.db.tables import metadata
from framegen.settings import get_settings

connection = context.config.attributes.get("connection")


def run(connection_to_use: Connection) -> None:
    context.configure(connection=connection_to_use, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


if connection is not None:
    run(connection)
else:
    engine = sync_engine(get_settings())
    try:
        with engine.connect() as new_connection:
            run(new_connection)
    finally:
        engine.dispose()
