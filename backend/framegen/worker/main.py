"""Worker entry point. Jobs arrive in T-08; until then the worker starts, waits and stops."""

import logging
import signal
from collections.abc import Callable

from framegen import __version__

log = logging.getLogger("framegen.worker")

STOP_SIGNALS = {signal.SIGTERM, signal.SIGINT}


def wait_for_stop_signal() -> None:
    """Blocks, without waking up, until SIGTERM or SIGINT arrives."""
    signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
    signal.sigwait(STOP_SIGNALS)


def run(wait_for_stop: Callable[[], None]) -> None:
    log.info("framegen worker %s started; no job queue yet", __version__)
    wait_for_stop()
    log.info("framegen worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run(wait_for_stop_signal)
