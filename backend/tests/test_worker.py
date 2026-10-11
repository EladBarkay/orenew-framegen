import logging

import pytest

from framegen.worker.main import run


def test_worker_runs_until_stopped(caplog: pytest.LogCaptureFixture) -> None:
    waited: list[int] = []
    with caplog.at_level(logging.INFO, logger="framegen.worker"):
        run(lambda: waited.append(1))
    assert waited == [1]
    assert "started" in caplog.text
    assert "stopped" in caplog.text
