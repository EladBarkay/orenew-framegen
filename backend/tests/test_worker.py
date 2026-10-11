import logging

import pytest

from framegen.worker.main import run


def test_worker_runs_until_stopped(caplog: pytest.LogCaptureFixture) -> None:
    polls = iter([False, False, True])
    with caplog.at_level(logging.INFO, logger="framegen.worker"):
        run(lambda: next(polls), poll_seconds=0)
    assert "started" in caplog.text
    assert "stopped" in caplog.text
