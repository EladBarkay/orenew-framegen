"""Worker entry point. Jobs arrive in T-08; until then the worker only proves it starts."""

import logging

from framegen import __version__

log = logging.getLogger("framegen.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("framegen worker %s started; no job queue yet", __version__)
