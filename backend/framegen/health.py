"""Readiness checks: can this process reach what it depends on?"""

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait

import psycopg

from framegen.settings import Settings
from framegen.storage.client import s3_client

log = logging.getLogger("framegen.health")

Check = Callable[[], None]
"""A check returns normally when the dependency works and raises when it does not."""

DEADLINE_SECONDS = 3.0
"""All checks together finish within this, below the 5 s health-check timeout in Compose."""


def database_check(settings: Settings) -> Check:
    def check() -> None:
        with psycopg.connect(settings.database_conninfo, connect_timeout=2) as conn:
            conn.execute("SELECT 1")

    return check


def storage_check(settings: Settings) -> Check:
    # Fail fast: no retries and short timeouts, so a hung storage cannot stall the check.
    client = s3_client(settings, connect_timeout=2, read_timeout=2, max_attempts=1)

    def check() -> None:
        client.head_bucket(Bucket=settings.s3_bucket)

    return check


def default_checks(settings: Settings) -> dict[str, Check]:
    return {"database": database_check(settings), "storage": storage_check(settings)}


class Readiness:
    """Runs the checks in parallel under one deadline and logs only when a result changes."""

    def __init__(self, checks: Mapping[str, Check], deadline: float = DEADLINE_SECONDS) -> None:
        self._checks = dict(checks)
        self._deadline = deadline
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(self._checks)))
        self._last: dict[str, str] = {}

    def run(self) -> dict[str, str]:
        futures = {name: self._pool.submit(check) for name, check in self._checks.items()}
        wait(futures.values(), timeout=self._deadline)
        results: dict[str, str] = {}
        for name, future in futures.items():
            if not future.done():
                results[name] = "unavailable"
                self._report(name, "unavailable", f"no answer within {self._deadline} s")
            elif (error := future.exception()) is not None:
                results[name] = "unavailable"
                self._report(name, "unavailable", f"{type(error).__name__}: {error}")
            else:
                results[name] = "ok"
                self._report(name, "ok", None)
        return results

    def _report(self, name: str, result: str, reason: str | None) -> None:
        previous = self._last.get(name)
        self._last[name] = result
        if result == previous:
            return
        if result == "ok":
            if previous is not None:
                log.info("readiness check %r recovered", name)
        else:
            log.warning("readiness check %r failed: %s", name, reason)
