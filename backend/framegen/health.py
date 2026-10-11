"""Readiness checks: can this process reach what it depends on?"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Mapping

import psycopg

from framegen.settings import Settings
from framegen.storage.client import s3_client

log = logging.getLogger("framegen.health")

Check = Callable[[], None]
"""A check returns normally when the dependency works and raises when it does not."""

DEADLINE_SECONDS = 3.0
"""All checks together answer within this, below the 5 s health-check timeout in Compose."""


def database_check(settings: Settings) -> Check:
    def check() -> None:
        with psycopg.connect(
            settings.database_conninfo,
            connect_timeout=2,
            options="-c statement_timeout=2000",
            keepalives=1,
            keepalives_idle=2,
            keepalives_interval=1,
            keepalives_count=1,
        ) as conn:
            conn.execute("SELECT 1")

    return check


def storage_check(settings: Settings) -> Check:
    # No retries, and timeouts that add up to less than the deadline.
    client = s3_client(settings, connect_timeout=1, read_timeout=1.5, max_attempts=1)

    def check() -> None:
        client.head_bucket(Bucket=settings.s3_bucket)

    return check


def default_checks(settings: Settings) -> dict[str, Check]:
    return {"database": database_check(settings), "storage": storage_check(settings)}


class _Probe:
    """Runs one check on its own thread, never more than one run at a time.

    Waiters are asyncio futures, resolved from the probe thread when its run ends, so
    nobody polls and no thread is held while waiting.
    """

    def __init__(self, check: Check) -> None:
        self._check = check
        self._lock = threading.Lock()
        self._running = False
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []
        self._outcome: tuple[str, str | None] = ("unavailable", "not checked yet")

    def wait_for_run(self) -> asyncio.Future[None]:
        """A future that resolves when the next or the current run ends.

        Starts a run unless one is still going (a dependency that hangs).
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self._lock:
            # Drop waiters that gave up (timed out) while a hung run was still going.
            self._waiters = [(lp, fut) for lp, fut in self._waiters if not fut.done()]
            self._waiters.append((loop, future))
            if self._running:
                return future
            self._running = True
        try:
            threading.Thread(target=self._run, daemon=True).start()
        except BaseException:
            self._finish(("unavailable", "could not start the check"))
            raise
        return future

    def outcome(self) -> tuple[str, str | None]:
        with self._lock:
            return self._outcome

    def _run(self) -> None:
        outcome: tuple[str, str | None] = ("unavailable", "the check stopped unexpectedly")
        try:
            self._check()
            outcome = ("ok", None)
        except BaseException as error:
            outcome = ("unavailable", f"{type(error).__name__}: {error}")
        finally:
            self._finish(outcome)

    def _finish(self, outcome: tuple[str, str | None]) -> None:
        with self._lock:
            self._outcome = outcome
            self._running = False
            waiters, self._waiters = self._waiters, []
        for loop, future in waiters:
            if not loop.is_closed():
                with contextlib.suppress(RuntimeError):  # the loop closed after the check
                    loop.call_soon_threadsafe(_resolve, future)


def _resolve(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


class Readiness:
    """Runs the checks in parallel under one deadline and logs only when a result changes.

    Each check has at most one thread running, however many requests ask and however long
    a dependency hangs, and waiting for the results does not hold any thread.
    """

    def __init__(self, checks: Mapping[str, Check], deadline: float = DEADLINE_SECONDS) -> None:
        self._probes = {name: _Probe(check) for name, check in checks.items()}
        self._deadline = deadline
        self._log_lock = threading.Lock()
        self._last: dict[str, str] = {}

    async def run(self) -> dict[str, str]:
        futures = {name: probe.wait_for_run() for name, probe in self._probes.items()}
        await asyncio.wait(futures.values(), timeout=self._deadline)
        results: dict[str, str] = {}
        for name, future in futures.items():
            if future.done():
                result, reason = self._probes[name].outcome()
            else:
                future.cancel()
                result, reason = "unavailable", f"no answer within {self._deadline} s"
            results[name] = result
            self._report(name, result, reason)
        return results

    def _report(self, name: str, result: str, reason: str | None) -> None:
        with self._log_lock:
            previous = self._last.get(name)
            self._last[name] = result
        if result == previous:
            return
        if result == "ok":
            if previous is not None:
                log.info("readiness check %r recovered", name)
        else:
            log.warning("readiness check %r failed: %s", name, reason)
