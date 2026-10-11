"""Runs a job's work and keeps its row in the jobs table up to date.

Each job is a row in ``jobs`` (what clients see) and a Procrastinate job (the queue). The
work itself is a plain async function that receives a ``Progress`` to report through; it
raises ``JobFailed`` for a failure clients should understand. Every change to the row
also sends a Postgres notification on ``JOB_EVENTS``, so whoever is following the job
learns about it at once.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.db.tables import jobs

log = logging.getLogger("framegen.jobs")

JOB_EVENTS = "framegen_job_events"
"""Postgres notification channel; the payload is the changed job's ID."""


class JobFailed(Exception):
    """The job cannot finish, for a reason the client can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Progress:
    """Handed to a job's work, to report how far it is."""

    def __init__(self, engine: AsyncEngine, job_id: str) -> None:
        self._engine = engine
        self._job_id = job_id

    async def report(self, fraction: float, step: str | None = None) -> None:
        await _change(self._engine, self._job_id, progress=min(max(fraction, 0.0), 1.0), step=step)


Work = Callable[[Progress], Awaitable[Mapping[str, Any] | None]]


async def run_job(engine: AsyncEngine, job_id: str, work: Work) -> None:
    """Marks the job running, runs ``work``, and records how it ended."""
    await _change(engine, job_id, status="running", started_at=datetime.now(UTC))
    try:
        result = await work(Progress(engine, job_id))
    except JobFailed as failure:
        await _finish(engine, job_id, error=(failure.code, failure.message))
        return
    except Exception:
        log.exception("job %s failed", job_id)
        await _finish(engine, job_id, error=("internal", "Something went wrong on our side."))
        return
    await _finish(engine, job_id, result=dict(result) if result is not None else None)


async def _finish(
    engine: AsyncEngine,
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: tuple[str, str] | None = None,
) -> None:
    values: dict[str, Any] = {"finished_at": datetime.now(UTC)}
    if error is None:
        values.update(status="succeeded", progress=1.0, step=None, result=result)
    else:
        values.update(status="failed", error_code=error[0], error_message=error[1][:500])
    await _change(engine, job_id, **values)


async def _change(engine: AsyncEngine, job_id: str, **values: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(update(jobs).where(jobs.c.id == job_id).values(**values))
        # Sent when the transaction commits, so a listener always reads the new state.
        await conn.execute(select(func.pg_notify(JOB_EVENTS, job_id)))
