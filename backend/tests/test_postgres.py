"""Tests against a real Postgres. Run with FRAMEGEN_TEST_POSTGRES=1 (CI does).

They use their own database, framegen_test, created fresh for each run, so a developer's
data is never touched.
"""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text

from framegen.api.idempotency import (
    KEPT_FOR,
    LOCK_TIMEOUT,
    InProgress,
    Mismatch,
    Replay,
    Started,
    StoredResponse,
)
from framegen.db import migrate
from framegen.db.engine import async_engine, sync_engine
from framegen.db.idempotency_store import PostgresIdempotencyStore
from framegen.settings import Settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("FRAMEGEN_TEST_POSTGRES"), reason="set FRAMEGEN_TEST_POSTGRES=1"
)

TEST_DB = "framegen_test"


@pytest.fixture(scope="module")
def settings() -> Iterator[Settings]:
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


def test_migrations_create_the_tables_and_can_be_undone(settings: Settings) -> None:
    engine = sync_engine(settings)
    assert "idempotency_keys" in inspect(engine).get_table_names()
    from alembic import command

    with engine.begin() as conn:
        command.downgrade(migrate.alembic_config(conn), "base")
    assert "idempotency_keys" not in inspect(engine).get_table_names()
    with engine.begin() as conn:
        migrate.upgrade(conn)
    assert "idempotency_keys" in inspect(engine).get_table_names()
    engine.dispose()


def test_store_follows_the_idempotency_rules(settings: Settings) -> None:
    async def scenario() -> None:
        engine = async_engine(settings)
        store = PostgresIdempotencyStore(engine)
        now = datetime.now(UTC)
        response = StoredResponse(201, [("content-type", "application/json")], b'{"id":1}')
        try:
            assert await store.begin("me", "a", "f1", now) == Started()
            assert await store.begin("me", "a", "f1", now) == InProgress()
            assert await store.begin("me", "a", "f2", now) == Mismatch()
            await store.complete("me", "a", response)
            assert await store.begin("me", "a", "f1", now) == Replay(response)
            # Keys belong to whoever sent them.
            assert await store.begin("someone-else", "a", "f2", now) == Started()
            # A first run that never finished may be taken over after the lock times out.
            assert await store.begin("me", "b", "f", now) == Started()
            assert await store.begin("me", "b", "f", now + LOCK_TIMEOUT) == Started()
            # A released key (server error) starts over.
            await store.release("me", "b")
            assert await store.begin("me", "b", "g", now) == Started()
            # An expired key is new again.
            assert await store.begin("me", "a", "f3", now + KEPT_FOR) == Started()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_first_requests_start_only_once(settings: Settings) -> None:
    async def scenario() -> list[object]:
        engine = async_engine(settings)
        store = PostgresIdempotencyStore(engine)
        now = datetime.now(UTC) + timedelta(minutes=1)
        try:
            return list(
                await asyncio.gather(*(store.begin("me", "race", "f", now) for _ in range(8)))
            )
        finally:
            await engine.dispose()

    results = asyncio.run(scenario())
    assert results.count(Started()) == 1
    assert results.count(InProgress()) == 7


def test_expired_keys_are_deleted_when_new_keys_arrive(settings: Settings) -> None:
    async def scenario() -> int:
        engine = async_engine(settings)
        store = PostgresIdempotencyStore(engine)
        now = datetime.now(UTC) + timedelta(days=10)
        try:
            await store.begin("me", "old", "f", now - KEPT_FOR - timedelta(seconds=1))
            await store.begin("me", "new", "f", now)
            async with engine.connect() as conn:
                found = await conn.execute(
                    text("SELECT count(*) FROM idempotency_keys WHERE key = 'old'")
                )
                return int(found.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == 0


def test_a_key_released_during_begin_starts_over(settings: Settings) -> None:
    async def scenario() -> list[object]:
        engine = async_engine(settings)
        store = PostgresIdempotencyStore(engine)
        now = datetime.now(UTC) + timedelta(days=20)
        try:
            results: list[object] = []
            for _ in range(20):
                await store.begin("me", "churn", "f", now)
                # Repeats race with the first request being released.
                outcome = await asyncio.gather(
                    store.release("me", "churn"),
                    *(store.begin("me", "churn", "f", now) for _ in range(4)),
                )
                results.extend(outcome[1:])
                await store.release("me", "churn")
            return results
        finally:
            await engine.dispose()

    results = asyncio.run(scenario())
    assert set(results) <= {Started(), InProgress()}
