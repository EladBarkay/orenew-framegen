"""Brings the database schema up to date. Run once when the deployment starts."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection

log = logging.getLogger("framegen.db")

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade(connection: Connection | None = None) -> None:
    command.upgrade(alembic_config(connection), "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    upgrade()
    log.info("database schema is up to date")
