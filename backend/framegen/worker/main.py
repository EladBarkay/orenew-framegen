"""Worker entry point. Jobs arrive in T-08; until then the worker starts, waits and stops."""

import logging
import signal
import time
from collections.abc import Callable

from framegen import __version__

log = logging.getLogger("framegen.worker")


def run(should_stop: Callable[[], bool], poll_seconds: float = 0.5) -> None:
    log.info("framegen worker %s started; no job queue yet", __version__)
    while not should_stop():
        time.sleep(poll_seconds)
    log.info("framegen worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stopping = False

    def request_stop(signum: int, frame: object) -> None:
        # Only set a flag: a signal handler must not take locks the main thread may hold.
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, request_stop)
    run(lambda: stopping)
