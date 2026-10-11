"""Accounts and browser sessions (DESIGN.md section 10.1, T-06).

A browser signs up or signs in and gets a session cookie: an opaque random token,
HttpOnly and SameSite=Lax, valid for SESSION_LIFETIME. Only its sha256 is stored, so
reading the database does not give working sessions. Workspace API keys (scripts) and
OAuth (third-party apps) come later and resolve to the same ``CurrentUser``.

Cross-site requests: SameSite=Lax keeps the cookie off cross-site POSTs, and a
state-changing request whose ``Origin`` names another site is refused as well.
"""

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response, Security, status
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.api.errors import ApiError
from framegen.db.tables import memberships, sessions, users, workspaces
from framegen.ids import new_id
from framegen.settings import Settings

SESSION_COOKIE = "framegen_session"
SESSION_LIFETIME = timedelta(days=30)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_hasher = PasswordHasher()
# Checked when the email is unknown, so a wrong address takes as long as a wrong password.
_UNUSED_HASH = _hasher.hash(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: str
    language: str


class User(BaseModel):
    id: str
    email: str
    name: str
    language: str


def normalise_email(value: str) -> str:
    email = value.strip().lower()
    local, at, domain = email.partition("@")
    if not at or not local or "." not in domain or any(c.isspace() for c in email):
        raise ValueError("not an email address")
    return email


class SignUp(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return normalise_email(value)


class SignIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def lower(cls, value: str) -> str:
        return value.strip().lower()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def hash_password(password: str) -> str:
    # Deliberately slow (argon2), so it runs off the event loop.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def check() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(check)


async def user_for_token(engine: AsyncEngine, token: str, now: datetime) -> CurrentUser | None:
    query = (
        select(users.c.id, users.c.email, users.c.name, users.c.language)
        .join(sessions, sessions.c.user_id == users.c.id)
        .where(sessions.c.token_hash == token_hash(token), sessions.c.expires_at > now)
    )
    async with engine.connect() as conn:
        row = (await conn.execute(query)).first()
    return CurrentUser(row.id, row.email, row.name, row.language) if row else None


_USER_STATE = "framegen_user"


async def resolve_user(scope: Any) -> CurrentUser | None:
    """The signed-in user of a request, looked up once and remembered on the request."""
    state = scope.setdefault("state", {})
    if _USER_STATE not in state:
        token = Request(scope).cookies.get(SESSION_COOKIE)
        user = None
        if token and len(token) <= 200:
            user = await user_for_token(scope["app"].state.engine, token, datetime.now(UTC))
        state[_USER_STATE] = user
    found: CurrentUser | None = state[_USER_STATE]
    return found


async def principal_from_session(scope: Any) -> str | None:
    """Who a request is for, as the idempotency middleware scopes its keys."""
    user = await resolve_user(scope)
    return f"user:{user.id}" if user else None


def require_same_site(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise ApiError(403, "cross_site_request", "Requests from other sites are not accepted.")


_session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Browser session, set by signUp and signIn.",
)


async def current_user(
    request: Request, _cookie: Annotated[str | None, Security(_session_cookie)]
) -> CurrentUser:
    require_same_site(request)
    user = await resolve_user(request.scope)
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in first.")
    return user


SignedIn = Annotated[CurrentUser, Depends(current_user)]


def engine_of(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


Engine = Annotated[AsyncEngine, Depends(engine_of)]
AppSettings = Annotated[Settings, Depends(settings_of)]

router = APIRouter(tags=["auth"], dependencies=[Depends(require_same_site)])


async def _start_session(
    engine: AsyncEngine, response: Response, settings: Settings, user_id: str
) -> None:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        # Each sign-in also clears that user's expired sessions, so they never pile up.
        await conn.execute(
            delete(sessions).where(sessions.c.user_id == user_id, sessions.c.expires_at <= now)
        )
        await conn.execute(
            insert(sessions).values(
                token_hash=token_hash(token),
                user_id=user_id,
                created_at=now,
                expires_at=now + SESSION_LIFETIME,
            )
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
    )


@router.post("/v1/auth/signup", operation_id="signUp", status_code=status.HTTP_201_CREATED)
async def sign_up(body: SignUp, response: Response, engine: Engine, settings: AppSettings) -> User:
    """Create an account with its personal workspace, and sign in."""
    password_hash = await hash_password(body.password)
    user_id, workspace_id = new_id("usr"), new_id("wsp")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert(users).values(
                    id=user_id, email=body.email, name=body.name, password_hash=password_hash
                )
            )
            await conn.execute(
                insert(workspaces).values(id=workspace_id, name="Personal", kind="personal")
            )
            await conn.execute(
                insert(memberships).values(workspace_id=workspace_id, user_id=user_id, role="owner")
            )
    except IntegrityError as error:
        raise ApiError(409, "email_taken", "An account with this email exists.") from error
    await _start_session(engine, response, settings, user_id)
    return User(id=user_id, email=body.email, name=body.name, language="en")


@router.post("/v1/auth/signin", operation_id="signIn")
async def sign_in(body: SignIn, response: Response, engine: Engine, settings: AppSettings) -> User:
    """Sign in with email and password; sets the session cookie."""
    async with engine.connect() as conn:
        row = (await conn.execute(select(users).where(users.c.email == body.email))).first()
    if not await verify_password(row.password_hash if row else _UNUSED_HASH, body.password):
        raise ApiError(401, "invalid_credentials", "The email or password is wrong.")
    assert row is not None  # the unused hash never verifies
    if _hasher.check_needs_rehash(row.password_hash):
        new_hash = await hash_password(body.password)
        async with engine.begin() as conn:
            await conn.execute(
                update(users).where(users.c.id == row.id).values(password_hash=new_hash)
            )
    await _start_session(engine, response, settings, row.id)
    return User(id=row.id, email=row.email, name=row.name, language=row.language)


@router.post("/v1/auth/signout", operation_id="signOut", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(request: Request, response: Response, engine: Engine) -> None:
    """End this browser's session. Safe to call when not signed in."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        async with engine.begin() as conn:
            await conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(token)))
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")


@router.get("/v1/me", operation_id="getMe")
async def me(user: SignedIn) -> User:
    """The signed-in user."""
    return User(id=user.id, email=user.email, name=user.name, language=user.language)
