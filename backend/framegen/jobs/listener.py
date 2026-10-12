"""Wakes whoever follows a job when the worker changes it (one listener per API process).

The worker sends a Postgres notification on JOB_EVENTS for every change to a job
(runner.py). One connection per API process listens for them and wakes the streams
following that job. If the connection is lost, it reconnects with growing pauses;
streams also re-read their job on a timer, so a missed notification only delays them.
"""

import asyncio
import contextlib
import logging
from collections import defaultdict

import psycopg

from framegen.jobs.runner import JOB_EVENTS

log = logging.getLogger("framegen.jobs")


class JobEvents:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._waiting: defaultdict[str, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Starts listening in the background; never waits for the database."""
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def wait(self, job_id: str, timeout: float) -> None:
        """Returns when the job changes, or after ``timeout`` seconds at most."""
        event = asyncio.Event()
        self._waiting[job_id].add(event)
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            pass
        finally:
            self._waiting[job_id].discard(event)
            if not self._waiting[job_id]:
                del self._waiting[job_id]

    def _wake(self, job_id: str) -> None:
        for event in self._waiting.get(job_id, ()):
            event.set()

    async def _listen(self) -> None:
        pause = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {JOB_EVENTS}")
                    pause = 1.0
                    async for note in conn.notifies():
                        self._wake(note.payload)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("job events: %s; listening again in %.0f s", error, pause)
            await asyncio.sleep(pause)
            pause = min(pause * 2, 30.0)
