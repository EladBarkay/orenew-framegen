"""Idempotency keys kept in Postgres, so every API process sees the same keys."""

import logging
from datetime import datetime

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.api.idempotency import (
    KEPT_FOR,
    LOCK_TIMEOUT,
    BeginResult,
    InProgress,
    Mismatch,
    Replay,
    Started,
    StoredResponse,
)
from framegen.db.tables import idempotency_keys as t

log = logging.getLogger("framegen.api")

PURGE_BATCH = 100
"""Expired keys deleted each time a new key is stored, so the table does not grow forever."""


class PostgresIdempotencyStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def begin(self, scope: str, key: str, fingerprint: str, now: datetime) -> BeginResult:
        # The row can vanish between the insert and the lock (the first request was released
        # in between); then simply try again.
        for _ in range(3):
            result = await self._try_begin(scope, key, fingerprint, now)
            if result is not None:
                if isinstance(result, Started):
                    await self._purge_expired(now)
                return result
        return InProgress()

    async def _try_begin(
        self, scope: str, key: str, fingerprint: str, now: datetime
    ) -> BeginResult | None:
        fresh = {
            "fingerprint": fingerprint,
            "status_code": None,
            "response_headers": None,
            "response_body": None,
            "created_at": now,
            "expires_at": now + KEPT_FOR,
        }
        async with self._engine.begin() as conn:
            inserted = await conn.execute(
                insert(t)
                .values(scope=scope, key=key, **fresh)
                .on_conflict_do_nothing()
                .returning(t.c.key)
            )
            if inserted.first() is not None:
                return Started()
            # Someone used this key before: decide under a row lock.
            row = (
                await conn.execute(
                    select(t).where(t.c.scope == scope, t.c.key == key).with_for_update()
                )
            ).first()
            if row is None:
                return None
            if row.expires_at <= now:
                await conn.execute(
                    update(t).where(t.c.scope == scope, t.c.key == key).values(**fresh)
                )
                return Started()
            if row.fingerprint != fingerprint:
                return Mismatch()
            if row.status_code is not None:
                headers = [(str(name), str(value)) for name, value in row.response_headers or []]
                return Replay(StoredResponse(row.status_code, headers, row.response_body or b""))
            if row.created_at <= now - LOCK_TIMEOUT:
                await conn.execute(
                    update(t).where(t.c.scope == scope, t.c.key == key).values(created_at=now)
                )
                return Started()
            return InProgress()

    async def _purge_expired(self, now: datetime) -> None:
        expired = (
            select(t.c.scope, t.c.key)
            .where(t.c.expires_at <= now)
            .limit(PURGE_BATCH)
            .with_for_update(skip_locked=True)
        )
        try:
            async with self._engine.begin() as conn:
                await conn.execute(delete(t).where(tuple_(t.c.scope, t.c.key).in_(expired)))
        except Exception:
            log.exception("could not delete expired idempotency keys")

    async def complete(self, scope: str, key: str, response: StoredResponse) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(t)
                .where(t.c.scope == scope, t.c.key == key)
                .values(
                    status_code=response.status_code,
                    response_headers=[list(pair) for pair in response.headers],
                    response_body=response.body,
                )
            )

    async def release(self, scope: str, key: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(t).where(t.c.scope == scope, t.c.key == key))
