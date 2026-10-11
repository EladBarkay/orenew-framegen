import logging

import pytest

from framegen.worker.main import main


def test_worker_starts(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="framegen.worker"):
        main()
    assert "worker" in caplog.text
