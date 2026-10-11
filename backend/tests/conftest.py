"""Shared fixtures. Tests that need Postgres run with FRAMEGEN_TEST_POSTGRES=1 (CI does).

They use their own database, framegen_test, created fresh for each run, so a developer's
data is never touched.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from framegen.db import migrate
from framegen.db.engine import sync_engine
from framegen.settings import Settings

TEST_DB = "framegen_test"


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    if not os.environ.get("FRAMEGEN_TEST_POSTGRES"):
        pytest.skip("set FRAMEGEN_TEST_POSTGRES=1")
    admin = create_engine(
        Settings().model_copy(update={"db_name": "postgres"}).database_url,
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    test_settings = Settings(db_name=TEST_DB)
    engine = sync_engine(test_settings)
    with engine.begin() as conn:
        migrate.upgrade(conn)
    engine.dispose()
    yield test_settings
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    admin.dispose()
