"""Shared fixtures. Tests that need Postgres run with FRAMEGEN_TEST_POSTGRES=1, those
that also need the S3 storage with FRAMEGEN_TEST_STORAGE=1, and the renderer's with
FRAMEGEN_TEST_CHROMIUM=1 (CI sets all three).

They use their own database (framegen_test) and bucket (framegen-test), created fresh for
each run, so a developer's data is never touched.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from framegen.db import migrate
from framegen.db.engine import sync_engine
from framegen.settings import Settings
from framegen.storage.client import s3_client
from framegen.storage.setup import ensure_bucket

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


TEST_BUCKET = "framegen-test"


@pytest.fixture(scope="session")
def storage_settings(settings: Settings) -> Iterator[Settings]:
    """Postgres and storage. Uploads go straight to the storage (no Caddy in tests)."""
    if not os.environ.get("FRAMEGEN_TEST_STORAGE"):
        pytest.skip("set FRAMEGEN_TEST_STORAGE=1")
    test_settings = settings.model_copy(
        update={"s3_bucket": TEST_BUCKET, "s3_public_url": settings.s3_endpoint_url}
    )
    client = s3_client(test_settings)
    ensure_bucket(test_settings, client)
    yield test_settings
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=TEST_BUCKET):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=TEST_BUCKET, Key=item["Key"])
    client.delete_bucket(Bucket=TEST_BUCKET)
