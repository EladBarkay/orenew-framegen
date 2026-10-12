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
from collections.abc import AsyncIterator

import psycopg

from framegen.jobs.runner import JOB_EVENTS

log = logging.getLogger("framegen.jobs")


class JobEvents:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._waiting: defaultdict[str, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self.listening = False
        """True while notifications arrive; streams then re-read their job less often."""

    def start(self) -> None:
        """Starts listening in the background; never waits for the database."""
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    @contextlib.asynccontextmanager
    async def follow(self, job_id: str) -> AsyncIterator["Changes"]:
        """Registers for the job's changes first, so none is missed between reading the
        job and waiting for the next change."""
        event = asyncio.Event()
        self._waiting[job_id].add(event)
        try:
            yield Changes(event)
        finally:
            self._waiting[job_id].discard(event)
            if not self._waiting[job_id]:
                del self._waiting[job_id]

    def _wake(self, job_id: str) -> None:
        for event in self._waiting.get(job_id, ()):
            event.set()

    def _wake_all(self) -> None:
        """When listening starts or stops, every stream re-reads its job: changes may
        have been missed meanwhile, and their re-read pace changes."""
        for waiting in self._waiting.values():
            for event in waiting:
                event.set()

    async def _listen(self) -> None:
        pause = 1.0
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo,
                    autocommit=True,
                    connect_timeout=5,
                    # Notice a connection that died silently (failover, NAT timeout) within
                    # about a minute, instead of waiting on it for ever.
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                ) as conn:
                    await conn.execute(f"LISTEN {JOB_EVENTS}")
                    pause = 1.0
                    self.listening = True
                    self._wake_all()
                    async for note in conn.notifies():
                        self._wake(note.payload)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("job events: %s; listening again in %.0f s", error, pause)
            finally:
                if self.listening:
                    self.listening = False
                    self._wake_all()
            await asyncio.sleep(pause)
            pause = min(pause * 2, 30.0)


class Changes:
    def __init__(self, event: asyncio.Event) -> None:
        self._event = event

    async def wait(self, timeout: float) -> None:
        """Returns when the job has changed since the last call, or after ``timeout``."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._event.wait(), timeout)
        self._event.clear()
