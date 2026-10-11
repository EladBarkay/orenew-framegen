"""Jobs through a real Procrastinate worker and Postgres."""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from procrastinate.exceptions import AppNotOpen
from sqlalchemy import insert, select

from framegen.db.engine import async_engine, sync_engine
from framegen.db.tables import jobs, workspaces
from framegen.jobs.queue import queue_app, start_job
from framegen.jobs.runner import JOB_EVENTS, JobFailed, Progress, run_job
from framegen.settings import Settings
from framegen.worker.main import run as run_worker


@pytest.fixture
def workspace_id(settings: Settings) -> Iterator[str]:
    workspace = f"wsp_test{uuid.uuid4().hex[:12]}"
    engine = sync_engine(settings)
    with engine.begin() as conn:
        conn.execute(insert(workspaces).values(id=workspace, name="Jobs", kind="studio"))
    engine.dispose()
    yield workspace


def job_row(settings: Settings, job_id: str) -> dict[str, Any]:
    engine = sync_engine(settings)
    with engine.connect() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().one()
    engine.dispose()
    return dict(row)


async def start_demo(settings: Settings, workspace_id: str, **arguments: Any) -> str:
    engine = async_engine(settings)
    app = queue_app(settings)
    try:
        async with app.open_async():
            return await start_job(
                app,
                engine,
                workspace_id=workspace_id,
                job_type="demo",
                arguments={"step_seconds": 0, **arguments},
                created_by=None,
            )
    finally:
        await engine.dispose()


def test_a_demo_job_runs_to_completion(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id, steps=4))
    assert job_row(settings, job_id)["status"] == "queued"

    async def follow() -> list[str]:
        async with await psycopg.AsyncConnection.connect(
            settings.database_conninfo, autocommit=True
        ) as listener:
            await listener.execute(f"LISTEN {JOB_EVENTS}")
            await run_worker(settings, wait=False)
            heard = []
            async for note in listener.notifies(timeout=0.5):
                heard.append(note.payload)
            return heard

    heard = asyncio.run(follow())
    row = job_row(settings, job_id)
    assert (row["status"], row["progress"], row["result"]) == ("succeeded", 1.0, {"steps": 4})
    assert row["started_at"] <= row["finished_at"]
    # Started, four steps, finished.
    assert heard.count(job_id) == 6


def test_a_failing_job_reports_its_code(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id, steps=4, fail_with="demo_failed"))
    asyncio.run(run_worker(settings, wait=False))
    row = job_row(settings, job_id)
    assert (row["status"], row["error_code"]) == ("failed", "demo_failed")
    assert row["progress"] == 0.5


def test_an_unexpected_error_is_internal(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id))  # left queued; run directly

    async def broken(progress: Progress) -> None:
        raise RuntimeError("bug")

    async def scenario() -> None:
        engine = async_engine(settings)
        try:
            await run_job(engine, job_id, broken)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    row = job_row(settings, job_id)
    assert (row["status"], row["error_code"]) == ("failed", "internal")
    assert "bug" not in (row["error_message"] or "")


def test_a_job_the_queue_cannot_take_is_recorded_as_failed(
    settings: Settings, workspace_id: str
) -> None:
    async def scenario() -> None:
        engine = async_engine(settings)
        app = queue_app(settings)  # never opened: deferring fails
        try:
            with pytest.raises(AppNotOpen):
                await start_job(
                    app,
                    engine,
                    workspace_id=workspace_id,
                    job_type="demo",
                    arguments={},
                    created_by=None,
                )
            async with engine.connect() as conn:
                row = (
                    (await conn.execute(select(jobs).where(jobs.c.workspace_id == workspace_id)))
                    .mappings()
                    .one()
                )
            assert (row["status"], row["error_code"]) == ("failed", "queue_unavailable")
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_job_failed_carries_code_and_message() -> None:
    failure = JobFailed("provider_refused", "The provider refused the prompt.")
    assert (failure.code, str(failure)) == ("provider_refused", "The provider refused the prompt.")


def run_directly(settings: Settings, job_id: str, work: Any) -> None:
    async def scenario() -> None:
        engine = async_engine(settings)
        try:
            await run_job(engine, job_id, work)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_only_a_queued_job_runs(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id))
    ran: list[int] = []

    async def work(progress: Progress) -> None:
        ran.append(1)

    run_directly(settings, job_id, work)
    run_directly(settings, job_id, work)  # delivered again: already done, skipped
    assert ran == [1]


def test_a_cancelled_job_is_recorded_as_interrupted(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id))

    async def work(progress: Progress) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run_directly(settings, job_id, work)
    row = job_row(settings, job_id)
    assert (row["status"], row["error_code"]) == ("failed", "interrupted")


def test_odd_progress_reports_are_made_safe(settings: Settings, workspace_id: str) -> None:
    job_id = asyncio.run(start_demo(settings, workspace_id))

    async def work(progress: Progress) -> None:
        await progress.report(float("nan"), "x" * 500)
        raise JobFailed("stop_here", "Stopped to look at the progress.")

    run_directly(settings, job_id, work)
    row = job_row(settings, job_id)
    assert (row["error_code"], row["progress"], len(row["step"])) == ("stop_here", 0.0, 200)


def test_an_unknown_job_type_is_refused(settings: Settings, workspace_id: str) -> None:
    with pytest.raises(ValueError, match="demoo"):
        asyncio.run(start_demo_of_type(settings, workspace_id, "demoo"))


async def start_demo_of_type(settings: Settings, workspace_id: str, job_type: str) -> str:
    engine = async_engine(settings)
    try:
        return await start_job(
            queue_app(settings),
            engine,
            workspace_id=workspace_id,
            job_type=job_type,
            arguments={},
            created_by=None,
        )
    finally:
        await engine.dispose()
