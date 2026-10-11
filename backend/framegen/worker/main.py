"""Worker entry point. Jobs arrive in T-08; until then the worker starts, waits and stops."""

import logging
import signal
import threading

from framegen import __version__

log = logging.getLogger("framegen.worker")


def run(stop: threading.Event) -> None:
    log.info("framegen worker %s started; no job queue yet", __version__)
    stop.wait()
    log.info("framegen worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)
