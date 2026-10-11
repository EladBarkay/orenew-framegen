"""Worker entry point: runs queued jobs until SIGTERM or SIGINT (DESIGN.md section 9.1).

On a stop signal the worker takes no new jobs and lets running ones finish, for up to
STOP_GRACE seconds; Procrastinate handles the signals.
"""

import asyncio
import logging

from framegen import __version__
from framegen.db.engine import async_engine
from framegen.jobs import tasks
from framegen.jobs.queue import queue_app
from framegen.settings import Settings, get_settings

log = logging.getLogger("framegen.worker")

STOP_GRACE = 30.0


async def run(settings: Settings, *, wait: bool = True) -> None:
    """Runs jobs. With ``wait=False``, returns once the queue is empty (for tests)."""
    engine = async_engine(settings)
    tasks.engine = engine
    app = queue_app(settings)
    log.info("framegen worker %s started", __version__)
    try:
        async with app.open_async():
            await app.run_worker_async(
                wait=wait,
                install_signal_handlers=wait,
                shutdown_graceful_timeout=STOP_GRACE,
            )
    finally:
        tasks.engine = None
        await engine.dispose()
        log.info("framegen worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(get_settings()))
