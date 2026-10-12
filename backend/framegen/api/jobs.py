"""Jobs: long work runs in the worker; the API answers at once (DESIGN.md section 10.1).

A route that starts long work answers ``202 Accepted`` with the job and a ``Location``
header. The client then follows the job with ``getJob`` until its status is
``succeeded`` (the ``result`` is there) or ``failed`` (the ``error`` says why). The
progress stream (``/events``) comes with T-08c.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.api.access import MemberAccess
from framegen.api.auth import Engine
from framegen.api.errors import ApiError
from framegen.db.tables import jobs
from framegen.jobs.queue import start_job

router = APIRouter(tags=["jobs"])


class JobError(BaseModel):
    code: str = Field(description="Stable, for programs; as in API errors.")
    message: str = Field(description="An English hint for developers.")


class Job(BaseModel):
    id: str
    type: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: float = Field(ge=0, le=1)
    step: str | None = Field(description="What the job is doing now, in English.")
    result: dict[str, Any] | None = Field(description="Set when the job succeeded.")
    error: JobError | None = Field(description="Set when the job failed.")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DemoJob(BaseModel):
    steps: int = Field(default=5, ge=1, le=20)
    fail_with: str | None = Field(
        default=None,
        max_length=64,
        pattern="^[a-z_]+$",
        description="Fail halfway with this error code, to try out error handling.",
    )


JobId = Annotated[str, Path(max_length=40, description="The job's ID.")]


def job_from_row(row: Any) -> Job:
    return Job(
        id=row["id"],
        type=row["type"],
        status=row["status"],
        progress=row["progress"],
        step=row["step"],
        result=row["result"],
        error=(
            JobError(code=row["error_code"], message=row["error_message"] or "")
            if row["error_code"]
            else None
        ),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


async def find_job(engine: AsyncEngine, workspace_id: str, job_id: str) -> Job:
    query = select(jobs).where(jobs.c.workspace_id == workspace_id, jobs.c.id == job_id)
    async with engine.connect() as conn:
        row = (await conn.execute(query)).mappings().first()
    if row is None:
        raise ApiError(404, "job_not_found", "No such job.")
    return job_from_row(row)


@router.post(
    "/v1/workspaces/{workspace_id}/jobs/demo",
    operation_id="startDemoJob",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_demo_job(
    body: DemoJob, access: MemberAccess, engine: Engine, request: Request, response: Response
) -> Job:
    """Start a job that only counts through its steps, for checking that jobs work in a
    deployment and for trying out a client. It uses no AI and costs nothing."""
    try:
        job_id = await start_job(
            request.app.state.queue,
            engine,
            workspace_id=access.workspace_id,
            job_type="demo",
            arguments={"steps": body.steps, "fail_with": body.fail_with},
            created_by=access.user.id,
        )
    except Exception as error:
        raise ApiError(503, "queue_unavailable", "The job could not be queued.") from error
    response.headers["Location"] = f"/v1/workspaces/{access.workspace_id}/jobs/{job_id}"
    return await find_job(engine, access.workspace_id, job_id)


@router.get("/v1/workspaces/{workspace_id}/jobs/{job_id}", operation_id="getJob")
async def get_job(job_id: JobId, access: MemberAccess, engine: Engine) -> Job:
    """A job's status, progress, and its result or error once it has ended."""
    return await find_job(engine, access.workspace_id, job_id)
