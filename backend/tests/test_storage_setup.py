import pytest

from framegen.storage import setup


def test_storage_init_retries_until_storage_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def flaky_ensure_bucket(settings: object) -> bool:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("not yet")
        return True

    monkeypatch.setattr(setup, "ensure_bucket", flaky_ensure_bucket)
    setup.main(attempts=5, first_wait=0)
    assert len(calls) == 3


def test_storage_init_gives_up_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings: object) -> bool:
        raise ConnectionError("down")

    monkeypatch.setattr(setup, "ensure_bucket", broken)
    with pytest.raises(ConnectionError):
        setup.main(attempts=2, first_wait=0)
