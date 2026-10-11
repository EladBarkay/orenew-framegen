from typing import Any

from framegen.settings import Settings
from framegen.storage.client import s3_client


def test_total_attempts_counts_the_first_try() -> None:
    client = s3_client(Settings(), total_attempts=1)
    config: Any = client.meta.config  # the stubs do not describe the retries settings
    assert config.retries["total_max_attempts"] == 1
