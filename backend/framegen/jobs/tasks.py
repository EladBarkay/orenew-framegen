"""The tasks the worker runs. Each takes the job's ID first and runs through ``run_job``.

The worker sets ``engine`` before it starts taking jobs.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.jobs.runner import JobFailed, Progress, run_job

engine: AsyncEngine | None = None


def _engine() -> AsyncEngine:
    if engine is None:
        raise RuntimeError("the worker has not set framegen.jobs.tasks.engine")
    return engine


async def demo(
    job_id: str, steps: int = 5, step_seconds: float = 0.2, fail_with: str | None = None
) -> None:
    """Counts through ``steps`` steps, for checking that jobs work end to end. With
    ``fail_with``, fails halfway with that error code."""

    async def work(progress: Progress) -> dict[str, int]:
        for done in range(steps):
            if fail_with and done == steps // 2:
                raise JobFailed(fail_with, "The demo job was asked to fail.")
            await asyncio.sleep(step_seconds)
            await progress.report((done + 1) / steps, f"step {done + 1} of {steps}")
        return {"steps": steps}

    await run_job(_engine(), job_id, work)


TASKS: dict[str, Callable[..., Awaitable[Any]]] = {"demo": demo}
"""Job type → task. The job type is also the task's name on the queue."""
