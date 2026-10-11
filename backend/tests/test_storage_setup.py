from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ParamValidationError

from framegen.storage import setup


def test_storage_init_retries_until_storage_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def flaky_ensure_bucket(settings: object, client: object) -> bool:
        calls.append(1)
        if len(calls) < 3:
            raise EndpointConnectionError(endpoint_url="http://storage:9000")
        return True

    monkeypatch.setattr(setup, "ensure_bucket", flaky_ensure_bucket)
    setup.main(attempts=5, first_wait=0)
    assert len(calls) == 3


def test_storage_init_gives_up_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings: object, client: object) -> bool:
        raise EndpointConnectionError(endpoint_url="http://storage:9000")

    monkeypatch.setattr(setup, "ensure_bucket", broken)
    with pytest.raises(EndpointConnectionError):
        setup.main(attempts=2, first_wait=0)


def test_errors_that_waiting_cannot_fix_fail_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def forbidden(settings: object, client: object) -> bool:
        calls.append(1)
        response: Any = {"Error": {"Code": "403"}, "ResponseMetadata": {"HTTPStatusCode": 403}}
        raise ClientError(response, "HeadBucket")

    monkeypatch.setattr(setup, "ensure_bucket", forbidden)
    with pytest.raises(ClientError):
        setup.main(attempts=5, first_wait=0)
    assert calls == [1]


def test_wrong_settings_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def invalid(settings: object, client: object) -> bool:
        calls.append(1)
        raise ParamValidationError(report="Invalid bucket name")

    monkeypatch.setattr(setup, "ensure_bucket", invalid)
    with pytest.raises(ParamValidationError):
        setup.main(attempts=5, first_wait=0)
    assert calls == [1]
