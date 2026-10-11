import logging
import threading

import pytest

from framegen.worker.main import run


def test_worker_runs_until_stopped(caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    stop.set()
    with caplog.at_level(logging.INFO, logger="framegen.worker"):
        run(stop)
    assert "started" in caplog.text
    assert "stopped" in caplog.text
