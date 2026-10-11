"""The one place where workspace roles are checked (DESIGN.md D5).

Every route under ``/v1/workspaces/{workspace_id}`` takes one of ``MemberAccess``,
``AdminAccess`` or ``OwnerAccess``. A workspace the user does not belong to answers 404,
the same as one that does not exist, so IDs reveal nothing. Finer permissions can be
added here later without touching the routes.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Path
from sqlalchemy import select

from framegen.api.auth import CurrentUser, Engine, SignedIn
from framegen.api.errors import ApiError
from framegen.db.tables import memberships, workspaces

Role = Literal["member", "admin", "owner"]
WorkspaceKind = Literal["personal", "studio"]
RANK: dict[str, int] = {"member": 1, "admin": 2, "owner": 3}


@dataclass(frozen=True)
class WorkspaceAccess:
    user: CurrentUser
    workspace_id: str
    name: str
    kind: WorkspaceKind
    role: Role

    def require(self, minimum: Role) -> None:
        if RANK[self.role] < RANK[minimum]:
            raise ApiError(
                403,
                "role_required",
                f"This needs the {minimum} role in the workspace.",
                {"required": minimum, "role": self.role},
            )


WorkspaceId = Annotated[str, Path(max_length=40, description="The workspace's ID.")]


def _requires(minimum: Role) -> Callable[..., Awaitable[WorkspaceAccess]]:
    async def access(workspace_id: WorkspaceId, user: SignedIn, engine: Engine) -> WorkspaceAccess:
        query = (
            select(workspaces.c.name, workspaces.c.kind, memberships.c.role)
            .join(memberships, memberships.c.workspace_id == workspaces.c.id)
            .where(workspaces.c.id == workspace_id, memberships.c.user_id == user.id)
        )
        async with engine.connect() as conn:
            row = (await conn.execute(query)).first()
        if row is None:
            raise ApiError(404, "workspace_not_found", "No such workspace.")
        found = WorkspaceAccess(user, workspace_id, row.name, row.kind, row.role)
        found.require(minimum)
        return found

    return access


MemberAccess = Annotated[WorkspaceAccess, Depends(_requires("member"))]
AdminAccess = Annotated[WorkspaceAccess, Depends(_requires("admin"))]
OwnerAccess = Annotated[WorkspaceAccess, Depends(_requires("owner"))]
