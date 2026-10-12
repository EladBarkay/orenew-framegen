"""The job queue (Procrastinate, in Postgres) and how jobs are put on it."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import procrastinate
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.db.tables import jobs
from framegen.ids import new_id
from framegen.jobs import tasks
from framegen.settings import Settings


def queue_app(settings: Settings) -> procrastinate.App:
    """The Procrastinate app. Open it (``open_async``) before deferring or working."""
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=settings.database_conninfo)
    )
    # Registered on each app afresh (not through a shared Blueprint), so several apps
    # in one process, as in tests, all know the same names.
    for name, function in tasks.TASKS.items():
        app.task(name=name)(function)
    return app


async def start_job(
    app: procrastinate.App,
    engine: AsyncEngine,
    *,
    workspace_id: str,
    job_type: str,
    arguments: Mapping[str, Any],
    created_by: str | None,
) -> str:
    """Records a queued job and puts its task on the queue. Returns the job's ID.

    If the queue cannot take it, the job is recorded as failed (queue_unavailable) and
    the error is raised. Should the queue have taken it after all (the answer was lost),
    either the worker skips it (only queued jobs are run) or, when a worker started it
    first, the job simply goes on and its ID is returned.
    """
    if job_type not in tasks.TASKS:
        raise ValueError(f"no task for job type {job_type!r}")
    job_id = new_id("job")
    async with engine.begin() as conn:
        await conn.execute(
            insert(jobs).values(
                id=job_id,
                workspace_id=workspace_id,
                type=job_type,
                status="queued",
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
        )
    try:
        await app.configure_task(job_type).defer_async(job_id=job_id, **arguments)
    except Exception:
        async with engine.begin() as conn:
            marked = await conn.execute(
                update(jobs)
                .where(jobs.c.id == job_id, jobs.c.status == "queued")
                .values(
                    status="failed",
                    error_code="queue_unavailable",
                    error_message="The job could not be queued.",
                    finished_at=datetime.now(UTC),
                )
                .returning(jobs.c.id)
            )
            already_claimed = marked.first() is None
        if already_claimed:
            # The queue took it after all and a worker already started it.
            return job_id
        raise
    return job_id
