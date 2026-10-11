"""Workspaces, their members and invitations (DESIGN.md sections 2 and 11, T-06).

Every user has one personal workspace. Studios are workspaces with several members, each
an owner, admin or member. Admins invite people and manage members; only owners can make
or remove owners, and a workspace always keeps at least one owner.

Invitations are answered with a token, which the inviting admin passes on (email sending
comes later). The invitee signs in with the invited address and accepts with the token.
"""

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Row, Select, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from framegen.api.access import (
    RANK,
    AdminAccess,
    MemberAccess,
    Role,
    WorkspaceAccess,
    WorkspaceKind,
)
from framegen.api.auth import Engine, SignedIn, User, normalise_email, token_hash
from framegen.api.errors import ApiError
from framegen.api.pagination import DEFAULT_LIMIT, Cursor, Limit, Page, after_key, keyset_page
from framegen.db.tables import invitations, memberships, users, workspaces
from framegen.ids import new_id

INVITATION_LIFETIME = timedelta(days=7)

router = APIRouter(tags=["workspaces"])


class Workspace(BaseModel):
    id: str
    name: str
    kind: WorkspaceKind
    role: Role = Field(description="The signed-in user's role in this workspace.")


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Member(BaseModel):
    user: User
    role: Role
    joined_at: datetime


class MemberUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: str = Field(max_length=254)
    role: Role = "member"

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return normalise_email(value)


class Invitation(BaseModel):
    id: str
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime


class CreatedInvitation(Invitation):
    token: str = Field(description="Give this to the invitee. It is shown only once.")


class InvitationAccept(BaseModel):
    token: str = Field(max_length=200)


UserId = Annotated[str, Path(max_length=40, description="The member's user ID.")]
InvitationId = Annotated[str, Path(max_length=40, description="The invitation's ID.")]


def _workspace(access: WorkspaceAccess) -> Workspace:
    return Workspace(id=access.workspace_id, name=access.name, kind=access.kind, role=access.role)


@router.get("/v1/workspaces", operation_id="listWorkspaces")
async def list_workspaces(
    user: SignedIn, engine: Engine, limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None
) -> Page[Workspace]:
    """The workspaces the signed-in user belongs to, with their role in each."""
    after = after_key(cursor)
    query = (
        select(workspaces.c.id, workspaces.c.name, workspaces.c.kind, memberships.c.role)
        .join(memberships, memberships.c.workspace_id == workspaces.c.id)
        .where(memberships.c.user_id == user.id, workspaces.c.id > after)
        .order_by(workspaces.c.id)
        .limit(limit + 1)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    items = [Workspace(id=r.id, name=r.name, kind=r.kind, role=r.role) for r in rows]
    return keyset_page(items, limit, lambda w: w.id)


@router.post("/v1/workspaces", operation_id="createWorkspace", status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreate, user: SignedIn, engine: Engine) -> Workspace:
    """Create a studio workspace; the signed-in user becomes its owner."""
    workspace_id = new_id("wsp")
    async with engine.begin() as conn:
        await conn.execute(
            insert(workspaces).values(id=workspace_id, name=body.name, kind="studio")
        )
        await conn.execute(
            insert(memberships).values(workspace_id=workspace_id, user_id=user.id, role="owner")
        )
    return Workspace(id=workspace_id, name=body.name, kind="studio", role="owner")


@router.get("/v1/workspaces/{workspace_id}", operation_id="getWorkspace")
async def get_workspace(access: MemberAccess) -> Workspace:
    return _workspace(access)


@router.patch("/v1/workspaces/{workspace_id}", operation_id="updateWorkspace")
async def update_workspace(body: WorkspaceUpdate, access: AdminAccess, engine: Engine) -> Workspace:
    """Rename the workspace (admins)."""
    async with engine.begin() as conn:
        await conn.execute(
            update(workspaces).where(workspaces.c.id == access.workspace_id).values(name=body.name)
        )
    return Workspace(id=access.workspace_id, name=body.name, kind=access.kind, role=access.role)


@router.get("/v1/workspaces/{workspace_id}/members", operation_id="listMembers")
async def list_members(
    access: MemberAccess, engine: Engine, limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None
) -> Page[Member]:
    after = after_key(cursor)
    query = (
        _member_query(access.workspace_id)
        .where(users.c.id > after)
        .order_by(users.c.id)
        .limit(limit + 1)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    return keyset_page([_member(row) for row in rows], limit, lambda m: m.user.id)


@router.patch("/v1/workspaces/{workspace_id}/members/{user_id}", operation_id="updateMember")
async def update_member(
    user_id: UserId, body: MemberUpdate, access: AdminAccess, engine: Engine
) -> Member:
    """Change a member's role (admins; making or unmaking an owner needs an owner)."""
    async with engine.begin() as conn:
        access = await _lock(conn, access)
        access.require("admin")
        current = await _role_of(conn, access.workspace_id, user_id)
        if "owner" in (current, body.role):
            access.require("owner")
        if current == "owner" and body.role != "owner":
            await _keep_an_owner(conn, access.workspace_id)
        await conn.execute(
            update(memberships)
            .where(memberships.c.workspace_id == access.workspace_id)
            .where(memberships.c.user_id == user_id)
            .values(role=body.role)
        )
        row = (
            await conn.execute(_member_query(access.workspace_id).where(users.c.id == user_id))
        ).one()
    return _member(row)


@router.delete(
    "/v1/workspaces/{workspace_id}/members/{user_id}",
    operation_id="removeMember",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(user_id: UserId, access: MemberAccess, engine: Engine) -> None:
    """Remove a member (admins; removing an owner needs an owner). Anyone may leave."""
    async with engine.begin() as conn:
        access = await _lock(conn, access)
        current = await _role_of(conn, access.workspace_id, user_id)
        if user_id != access.user.id:
            access.require("owner" if current == "owner" else "admin")
        if current == "owner":
            await _keep_an_owner(conn, access.workspace_id)
        await conn.execute(
            delete(memberships)
            .where(memberships.c.workspace_id == access.workspace_id)
            .where(memberships.c.user_id == user_id)
        )


@router.post(
    "/v1/workspaces/{workspace_id}/invitations",
    operation_id="createInvitation",
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    body: InvitationCreate, access: AdminAccess, engine: Engine
) -> CreatedInvitation:
    """Invite someone by email to a studio (admins; inviting an owner needs an owner).

    A new invitation for the same address replaces the previous one.
    """
    if access.kind == "personal":
        raise ApiError(409, "personal_workspace", "A personal workspace has no other members.")
    if body.role == "owner":
        access.require("owner")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    invitation = CreatedInvitation(
        id=new_id("inv"),
        email=body.email,
        role=body.role,
        created_at=now,
        expires_at=now + INVITATION_LIFETIME,
        token=token,
    )
    async with engine.begin() as conn:
        already = await conn.execute(
            select(memberships.c.user_id)
            .join(users, users.c.id == memberships.c.user_id)
            .where(memberships.c.workspace_id == access.workspace_id, users.c.email == body.email)
        )
        if already.first() is not None:
            raise ApiError(409, "already_member", "This person is already a member.")
        # One invitation per address and workspace (a unique constraint): a new one replaces
        # the old, also when two arrive at once.
        replacing = {
            "id": invitation.id,
            "role": invitation.role,
            "token_hash": token_hash(token),
            "invited_by": access.user.id,
            "created_at": invitation.created_at,
            "expires_at": invitation.expires_at,
        }
        await conn.execute(
            pg_insert(invitations)
            .values(workspace_id=access.workspace_id, email=invitation.email, **replacing)
            .on_conflict_do_update(
                index_elements=[invitations.c.workspace_id, invitations.c.email], set_=replacing
            )
        )
    return invitation


@router.get("/v1/workspaces/{workspace_id}/invitations", operation_id="listInvitations")
async def list_invitations(
    access: AdminAccess, engine: Engine, limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None
) -> Page[Invitation]:
    """Invitations not yet accepted and not expired (admins)."""
    after = after_key(cursor)
    query = (
        select(invitations)
        .where(invitations.c.workspace_id == access.workspace_id)
        .where(invitations.c.expires_at > datetime.now(UTC), invitations.c.id > after)
        .order_by(invitations.c.id)
        .limit(limit + 1)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).all()
    items = [
        Invitation(
            id=r.id, email=r.email, role=r.role, created_at=r.created_at, expires_at=r.expires_at
        )
        for r in rows
    ]
    return keyset_page(items, limit, lambda i: i.id)


@router.delete(
    "/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
    operation_id="revokeInvitation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: InvitationId, access: AdminAccess, engine: Engine
) -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            delete(invitations)
            .where(invitations.c.workspace_id == access.workspace_id)
            .where(invitations.c.id == invitation_id)
            .returning(invitations.c.id)
        )
        if result.first() is None:
            raise ApiError(404, "invitation_not_found", "No such invitation.")


@router.post("/v1/invitations/accept", operation_id="acceptInvitation")
async def accept_invitation(body: InvitationAccept, user: SignedIn, engine: Engine) -> Workspace:
    """Join the workspace an invitation is for. The invitation is used up."""
    async with engine.begin() as conn:
        found = (
            await conn.execute(
                select(invitations, workspaces.c.name, workspaces.c.kind)
                .join(workspaces, workspaces.c.id == invitations.c.workspace_id)
                .where(invitations.c.token_hash == token_hash(body.token))
                .where(invitations.c.expires_at > datetime.now(UTC))
                .with_for_update(of=invitations)
            )
        ).first()
        if found is None:
            raise ApiError(404, "invitation_not_found", "The invitation is unknown or expired.")
        if found.email != user.email:
            raise ApiError(
                403,
                "invitation_for_another_email",
                "This invitation is for another email address; sign in with that one.",
            )
        await _lock_workspace(conn, found.workspace_id)
        # An invitation is only as good as its inviter's role now: one from someone since
        # removed or demoted no longer works.
        inviter = (
            await _member_role(conn, found.workspace_id, found.invited_by)
            if found.invited_by
            else None
        )
        needed: Role = "owner" if found.role == "owner" else "admin"
        if inviter is None or RANK[inviter] < RANK[needed]:
            raise ApiError(404, "invitation_not_found", "The invitation is unknown or expired.")
        joined = await conn.execute(
            pg_insert(memberships)
            .values(workspace_id=found.workspace_id, user_id=user.id, role=found.role)
            .on_conflict_do_nothing()
            .returning(memberships.c.role)
        )
        if joined.first() is None:
            # Nothing changes (the invitation stays for an admin to revoke), so a retry gets
            # the same answer; the member's role is changed by an admin instead.
            raise ApiError(409, "already_member", "You are already a member of this workspace.")
        await conn.execute(delete(invitations).where(invitations.c.id == found.id))
    return Workspace(id=found.workspace_id, name=found.name, kind=found.kind, role=found.role)


def _member_query(workspace_id: str) -> Select[tuple[str, str, str, str, str, datetime]]:
    return (
        select(
            users.c.id,
            users.c.email,
            users.c.name,
            users.c.language,
            memberships.c.role,
            memberships.c.created_at,
        )
        .join(memberships, memberships.c.user_id == users.c.id)
        .where(memberships.c.workspace_id == workspace_id)
    )


def _member(row: Row[tuple[str, str, str, str, str, datetime]]) -> Member:
    return Member(
        user=User(id=row.id, email=row.email, name=row.name, language=row.language),
        role=row.role,
        joined_at=row.created_at,
    )


async def _lock_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    """Lock the workspace row until the transaction ends.

    Every change to memberships takes this lock first, so they run one at a time per
    workspace: two owners demoting each other at once cannot leave it without an owner.
    """
    await conn.execute(
        select(workspaces.c.id).where(workspaces.c.id == workspace_id).with_for_update()
    )


async def _lock(conn: AsyncConnection, access: WorkspaceAccess) -> WorkspaceAccess:
    """Lock the workspace, then re-read the caller's role: it may have changed since the
    request was let in (a demotion or removal waiting on the same lock)."""
    await _lock_workspace(conn, access.workspace_id)
    role = await _member_role(conn, access.workspace_id, access.user.id)
    if role is None:
        raise ApiError(404, "workspace_not_found", "No such workspace.")
    return replace(access, role=role)


async def _role_of(conn: AsyncConnection, workspace_id: str, user_id: str) -> Role:
    role = await _member_role(conn, workspace_id, user_id)
    if role is None:
        raise ApiError(404, "member_not_found", "No such member in this workspace.")
    return role


async def _member_role(conn: AsyncConnection, workspace_id: str, user_id: str) -> Role | None:
    role: Role | None = (
        await conn.execute(
            select(memberships.c.role)
            .where(memberships.c.workspace_id == workspace_id)
            .where(memberships.c.user_id == user_id)
        )
    ).scalar_one_or_none()
    return role


async def _keep_an_owner(conn: AsyncConnection, workspace_id: str) -> None:
    """Refuse a change that would remove the workspace's last owner (workspace locked)."""
    owners = (
        await conn.execute(
            select(func.count())
            .select_from(memberships)
            .where(memberships.c.workspace_id == workspace_id, memberships.c.role == "owner")
        )
    ).scalar_one()
    if owners <= 1:
        raise ApiError(409, "last_owner", "A workspace needs at least one owner.")
