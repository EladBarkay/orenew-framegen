"""Jobs: long work runs in the worker; the API answers at once (DESIGN.md section 10.1).

A route that starts long work answers ``202 Accepted`` with the job and a ``Location``
header. The client then follows the job with ``getJob`` until its status is
``succeeded`` (the ``result`` is there) or ``failed`` (the ``error`` says why), or
reads ``getJobEvents``, a stream of server-sent events that ends with the job.
"""

import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.api.access import MemberAccess
from framegen.api.auth import SESSION_COOKIE, Engine, token_hash
from framegen.api.errors import ApiError
from framegen.db.tables import jobs, memberships, sessions
from framegen.jobs.listener import JobEvents
from framegen.jobs.queue import QueueUnavailable, start_job

log = logging.getLogger("framegen.api")

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
        pattern="^demo_[a-z_]+$",
        description=(
            "Fail halfway with this error code, to try out error handling. Starts with "
            "demo_, so it is never mistaken for a real failure."
        ),
    )


JobId = Annotated[str, Path(max_length=40, description="The job's ID.")]


def job_from_row(row: Any) -> Job:
    error = (
        {"code": row["error_code"], "message": row["error_message"] or ""}
        if row["error_code"]
        else None
    )
    return Job.model_validate({**row, "error": error})


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
    deployment and for trying out a client. It uses no AI and costs nothing. A workspace
    can have one demo job at a time, so the shared queue stays free for real work."""
    try:
        job_id = await start_job(
            request.app.state.queue,
            engine,
            workspace_id=access.workspace_id,
            job_type="demo",
            arguments={"steps": body.steps, "fail_with": body.fail_with},
            created_by=access.user.id,
        )
    except IntegrityError as error:
        # uq_jobs_one_active_demo: another demo job is queued or running.
        raise ApiError(
            409, "demo_job_running", "This workspace already has a demo job running."
        ) from error
    except QueueUnavailable as error:
        raise ApiError(
            503, "queue_unavailable", "The job could not be queued.", {"job_id": error.job_id}
        ) from error
    response.headers["Location"] = f"/v1/workspaces/{access.workspace_id}/jobs/{job_id}"
    return await find_job(engine, access.workspace_id, job_id)


@router.get("/v1/workspaces/{workspace_id}/jobs/{job_id}", operation_id="getJob")
async def get_job(job_id: JobId, access: MemberAccess, engine: Engine) -> Job:
    """A job's status, progress, and its result or error once it has ended."""
    return await find_job(engine, access.workspace_id, job_id)


FINISHED = {"succeeded", "failed"}
RECHECK_SECONDS = 2.0
"""How often a stream re-reads its job while notifications are not arriving."""
RECHECK_LISTENING_SECONDS = 30.0
"""The same while they arrive: only in case one was missed."""
KEEP_ALIVE_SECONDS = 15.0
"""A comment line this often keeps proxies from closing a quiet stream."""
MAX_STREAM_SECONDS = 600.0
"""A stream ends after this; clients reconnect and get the current state at once."""


@router.get(
    "/v1/workspaces/{workspace_id}/jobs/{job_id}/events",
    operation_id="getJobEvents",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Server-sent events. Each `job` event carries the job (as getJob returns "
                "it): first its current state, then each change. The stream ends after the "
                "job has succeeded or failed (clients should then stop following), or after "
                "10 minutes (reconnect to go on). Lines starting with ':' only keep the "
                "connection alive."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        204: {
            "description": (
                "A reconnect (with Last-Event-ID) to a job that has ended: nothing more will "
                "come, and browsers' EventSource stops reconnecting."
            )
        },
    },
)
async def get_job_events(
    job_id: JobId, access: MemberAccess, engine: Engine, request: Request
) -> Response:
    """Follow a job as it happens."""
    first = await find_job(engine, access.workspace_id, job_id)
    if first.status in FINISHED and "last-event-id" in request.headers:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    events: JobEvents = request.app.state.job_events
    token = request.cookies.get(SESSION_COOKIE, "")

    async def stream() -> AsyncIterator[str]:
        started = quiet_since = time.monotonic()
        sent, number = "", 0
        async with events.follow(job_id) as changes:
            # Read again now that changes are being followed: one made since `first` was
            # read would otherwise only be seen at the next re-read.
            try:
                job = await find_job(engine, access.workspace_id, job_id)
            except Exception:
                log.warning("job %s: stream ended early", job_id, exc_info=True)
                return
            while True:
                data = job.model_dump_json()
                if data != sent:
                    number += 1
                    yield f"id: {number}\nevent: job\ndata: {data}\n\n"
                    sent, quiet_since = data, time.monotonic()
                elif time.monotonic() - quiet_since >= KEEP_ALIVE_SECONDS:
                    yield ": keep-alive\n\n"
                    quiet_since = time.monotonic()
                if job.status in FINISHED or time.monotonic() - started >= MAX_STREAM_SECONDS:
                    return
                recheck = RECHECK_LISTENING_SECONDS if events.listening else RECHECK_SECONDS
                # Wake by the time the next keep-alive is due, counted from the last write.
                due = KEEP_ALIVE_SECONDS - (time.monotonic() - quiet_since)
                await changes.wait(max(0.0, min(recheck, due)))
                try:
                    if not await _still_allowed(engine, token, access.user.id, access.workspace_id):
                        return  # signed out, or no longer a member
                    job = await find_job(engine, access.workspace_id, job_id)
                except Exception:
                    # Gone (its workspace was deleted) or the database is unreachable: end
                    # the stream cleanly; a client that reconnects learns which.
                    log.warning("job %s: stream ended early", job_id, exc_info=True)
                    return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # No caching, and no buffering in proxies: each event goes out at once.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _still_allowed(engine: AsyncEngine, token: str, user_id: str, workspace_id: str) -> bool:
    """Whether the stream's session is still valid and its user still a member."""
    query = (
        select(memberships.c.user_id)
        .join(sessions, sessions.c.user_id == memberships.c.user_id)
        .where(memberships.c.workspace_id == workspace_id, memberships.c.user_id == user_id)
        .where(
            sessions.c.token_hash == token_hash(token), sessions.c.expires_at > datetime.now(UTC)
        )
    )
    async with engine.connect() as conn:
        return (await conn.execute(query)).first() is not None
