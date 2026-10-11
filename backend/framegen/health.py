"""Readiness checks: can this process reach what it depends on?"""

from collections.abc import Callable, Mapping

import psycopg

from framegen.settings import Settings
from framegen.storage.client import s3_client

Check = Callable[[], None]
"""A check returns normally when the dependency works and raises when it does not."""


def database_check(settings: Settings) -> Check:
    def check() -> None:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")

    return check


def storage_check(settings: Settings) -> Check:
    def check() -> None:
        s3_client(settings).head_bucket(Bucket=settings.s3_bucket)

    return check


def default_checks(settings: Settings) -> Mapping[str, Check]:
    return {"database": database_check(settings), "storage": storage_check(settings)}


def run_checks(checks: Mapping[str, Check]) -> dict[str, str]:
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception:
            results[name] = "unavailable"
    return results
