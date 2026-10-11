"""Readiness checks: can this process reach what it depends on?"""

import asyncio
import logging
import threading
import time
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
    """Runs one check on its own thread, never more than one run at a time."""

    def __init__(self, check: Check) -> None:
        self._check = check
        self._lock = threading.Lock()
        self._done: threading.Event | None = None
        self._outcome: tuple[str, str | None] = ("unavailable", "not checked yet")

    def start(self) -> threading.Event:
        """Starts a run unless one is still going (a hung dependency), and returns its event."""
        with self._lock:
            if self._done is None or self._done.is_set():
                self._done = threading.Event()
                threading.Thread(target=self._run, args=(self._done,), daemon=True).start()
            return self._done

    def outcome(self) -> tuple[str, str | None]:
        with self._lock:
            return self._outcome

    def _run(self, done: threading.Event) -> None:
        try:
            self._check()
            outcome: tuple[str, str | None] = ("ok", None)
        except Exception as error:
            outcome = ("unavailable", f"{type(error).__name__}: {error}")
        with self._lock:
            self._outcome = outcome
        done.set()


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
        events = {name: probe.start() for name, probe in self._probes.items()}
        give_up_at = time.monotonic() + self._deadline
        while not all(event.is_set() for event in events.values()):
            if time.monotonic() >= give_up_at:
                break
            await asyncio.sleep(0.02)
        results: dict[str, str] = {}
        for name, event in events.items():
            if event.is_set():
                result, reason = self._probes[name].outcome()
            else:
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
