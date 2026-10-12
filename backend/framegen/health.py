"""Readiness checks: can this process reach what it depends on?"""

import asyncio
import logging
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from typing import Literal

import psycopg

from framegen.settings import Settings
from framegen.storage.client import s3_client

log = logging.getLogger("framegen.health")

Check = Callable[[], None]
"""A check returns normally when the dependency works and raises when it does not."""

DEADLINE_SECONDS = 3.0
"""Readiness answers within this; a check still running then is reported unavailable."""


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
    # One try, with timeouts that add up to less than the deadline.
    client = s3_client(settings, connect_timeout=1, read_timeout=1.5, total_attempts=1)

    def check() -> None:
        client.head_bucket(Bucket=settings.s3_bucket)

    return check


def default_checks(settings: Settings) -> dict[str, Check]:
    return {"database": database_check(settings), "storage": storage_check(settings)}


CheckResult = Literal["ok", "unavailable"]
Outcome = tuple[CheckResult, str | None]
"""("ok", None) or ("unavailable", reason)."""


class _Probe:
    """Runs one check on its own thread, never more than one run at a time."""

    def __init__(self, check: Check) -> None:
        self._check = check
        self._lock = threading.Lock()
        self._current: Future[Outcome] | None = None
        self._waiting: asyncio.Future[Outcome] | None = None

    def current_run(self) -> tuple[Future[Outcome], asyncio.Future[Outcome]]:
        """The run still going (a dependency that hangs), or a new one, with one awaitable
        for it that every request shares: wrapping the run anew for each request would add
        a callback to it each time while it hangs. Call from the event loop."""
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._current is None or self._current.done():
                run: Future[Outcome] = Future()
                # Running from now on, so cancelling the awaitable cannot cancel the run.
                run.set_running_or_notify_cancel()
                self._current, self._waiting = run, None
                try:
                    threading.Thread(target=self._run, args=(run,), daemon=True).start()
                except RuntimeError as error:  # no thread available
                    run.set_result(("unavailable", f"could not start the check: {error}"))
            waiting = self._waiting
            if waiting is None or waiting.cancelled() or waiting.get_loop() is not loop:
                waiting = self._waiting = asyncio.wrap_future(self._current, loop=loop)
            return self._current, waiting

    def _run(self, run: Future[Outcome]) -> None:
        try:
            self._check()
            outcome: Outcome = ("ok", None)
        except BaseException as error:
            outcome = ("unavailable", f"{type(error).__name__}: {error}")
        run.set_result(outcome)


class Readiness:
    """Runs the checks in parallel under one deadline and logs only when a result changes.

    Each check has at most one thread running, however many requests ask and however long
    a dependency hangs, and waiting for the results does not hold any thread.
    """

    def __init__(self, checks: Mapping[str, Check], deadline: float = DEADLINE_SECONDS) -> None:
        self._probes = {name: _Probe(check) for name, check in checks.items()}
        self._deadline = deadline
        # Only the event-loop thread running run() touches this; probe threads never do.
        self._last: dict[str, CheckResult] = {}

    async def run(self) -> dict[str, CheckResult]:
        runs = {name: probe.current_run() for name, probe in self._probes.items()}
        if runs:
            # asyncio.wait never cancels: a run still going stays shared with later requests.
            await asyncio.wait([waiting for _, waiting in runs.values()], timeout=self._deadline)
        results: dict[str, CheckResult] = {}
        for name, (run, _) in runs.items():
            result: CheckResult
            reason: str | None
            if run.done():
                result, reason = run.result()
            else:
                result, reason = "unavailable", f"no answer within {self._deadline} s"
            results[name] = result
            self._report(name, result, reason)
        return results

    def _report(self, name: str, result: CheckResult, reason: str | None) -> None:
        previous = self._last.get(name)
        self._last[name] = result
        if result == previous:
            return
        if result == "ok":
            if previous is not None:
                log.info("readiness check %r recovered", name)
        else:
            log.warning("readiness check %r failed: %s", name, reason)
