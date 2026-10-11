"""Accounts, sessions, workspaces, roles and invitations, against a real Postgres."""

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

import framegen.api.workspaces as workspaces_module
from framegen.api.access import WorkspaceAccess
from framegen.api.app import create_app
from framegen.api.auth import SESSION_COOKIE, CurrentUser
from framegen.db.engine import async_engine, sync_engine
from framegen.db.tables import memberships
from framegen.settings import Settings

PASSWORD = "correct horse battery"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(readiness_checks={}, settings=settings)) as test_client:
        yield test_client


def new_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def sign_up(client: TestClient, email: str | None = None, name: str = "Dana") -> str:
    """Signs up a new user; returns the session token (the client is now signed in as them)."""
    client.cookies.clear()
    response = client.post(
        "/v1/auth/signup",
        json={"email": email or new_email(), "password": PASSWORD, "name": name},
    )
    assert response.status_code == 201, response.text
    token = client.cookies.get(SESSION_COOKIE)
    assert token
    return token


def act_as(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, token)


def studio(client: TestClient, name: str = "Studio") -> str:
    response = client.post("/v1/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["id"]
    return workspace_id


def invite_and_join(client: TestClient, admin: str, workspace_id: str, role: str = "member") -> str:
    """Invites a new user with ``role`` and has them accept; returns their session."""
    email = new_email()
    act_as(client, admin)
    invited = client.post(
        f"/v1/workspaces/{workspace_id}/invitations", json={"email": email, "role": role}
    )
    assert invited.status_code == 201, invited.text
    member = sign_up(client, email)
    accepted = client.post("/v1/invitations/accept", json={"token": invited.json()["token"]})
    assert accepted.status_code == 200, accepted.text
    return member


def user_id(client: TestClient, token: str) -> str:
    act_as(client, token)
    found: str = client.get("/v1/me").json()["id"]
    return found


def test_sign_up_creates_a_personal_workspace_and_signs_in(client: TestClient) -> None:
    email = new_email()
    sign_up(client, email.upper(), name="Noa")
    me = client.get("/v1/me").json()
    assert (me["email"], me["name"]) == (email, "Noa")
    assert me["id"].startswith("usr_")
    spaces = client.get("/v1/workspaces").json()["items"]
    assert [(w["kind"], w["role"]) for w in spaces] == [("personal", "owner")]


def test_the_session_cookie_is_http_only(settings: Settings) -> None:
    with TestClient(create_app(readiness_checks={}, settings=settings)) as client:
        response = client.post(
            "/v1/auth/signup", json={"email": new_email(), "password": PASSWORD, "name": "A"}
        )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_an_email_is_used_once(client: TestClient) -> None:
    email = new_email()
    sign_up(client, email)
    again = client.post("/v1/auth/signup", json={"email": email, "password": PASSWORD, "name": "B"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "email_taken"


def test_sign_in_and_out(client: TestClient) -> None:
    email = new_email()
    sign_up(client, email)
    client.post("/v1/auth/signout")
    assert client.get("/v1/me").status_code == 401

    wrong = client.post("/v1/auth/signin", json={"email": email, "password": "wrong password"})
    unknown = client.post("/v1/auth/signin", json={"email": new_email(), "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()

    signed_in = client.post("/v1/auth/signin", json={"email": email, "password": PASSWORD})
    assert signed_in.status_code == 200
    assert client.get("/v1/me").json()["email"] == email


def test_a_signed_out_session_stops_working(client: TestClient) -> None:
    token = sign_up(client)
    client.post("/v1/auth/signout")
    act_as(client, token)
    assert client.get("/v1/me").status_code == 401


def test_weak_input_is_refused(client: TestClient) -> None:
    short = client.post(
        "/v1/auth/signup", json={"email": new_email(), "password": "short", "name": "A"}
    )
    not_email = client.post(
        "/v1/auth/signup", json={"email": "not-an-email", "password": PASSWORD, "name": "A"}
    )
    assert short.status_code == not_email.status_code == 422


def test_requests_from_another_site_are_refused(client: TestClient) -> None:
    sign_up(client)
    response = client.post(
        "/v1/workspaces", json={"name": "X"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site_request"
    for origin in ("http://testserver", "HTTP://TestServer:80"):
        same_site = client.post("/v1/workspaces", json={"name": "X"}, headers={"Origin": origin})
        assert same_site.status_code == 201, origin


def test_a_member_cannot_reach_another_workspace(client: TestClient) -> None:
    owner = sign_up(client)
    owner_id = user_id(client, owner)
    theirs = studio(client)
    invitation = client.post(
        f"/v1/workspaces/{theirs}/invitations", json={"email": new_email()}
    ).json()

    sign_up(client)
    mine = studio(client)
    for method, path, body in [
        ("GET", f"/v1/workspaces/{theirs}", None),
        ("PATCH", f"/v1/workspaces/{theirs}", {"name": "Mine now"}),
        ("GET", f"/v1/workspaces/{theirs}/members", None),
        ("GET", f"/v1/workspaces/{theirs}/invitations", None),
        ("POST", f"/v1/workspaces/{theirs}/invitations", {"email": new_email()}),
        ("DELETE", f"/v1/workspaces/{theirs}/invitations/{invitation['id']}", None),
        ("DELETE", f"/v1/workspaces/{theirs}/members/{owner_id}", None),
    ]:
        response = client.request(method, path, json=body)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["error"]["code"] == "workspace_not_found"
    listed = {w["id"] for w in client.get("/v1/workspaces").json()["items"]}
    assert mine in listed and theirs not in listed

    # And the owner's workspace is untouched.
    act_as(client, owner)
    assert client.get(f"/v1/workspaces/{theirs}").json()["name"] == "Studio"
    assert len(client.get(f"/v1/workspaces/{theirs}/members").json()["items"]) == 1


def test_inviting_members_into_a_studio(client: TestClient) -> None:
    owner = sign_up(client)
    workspace_id = studio(client, "Light & Lace")
    member = invite_and_join(client, owner, workspace_id)

    act_as(client, member)
    joined = client.get(f"/v1/workspaces/{workspace_id}").json()
    assert (joined["name"], joined["role"]) == ("Light & Lace", "member")
    roles = sorted(
        m["role"] for m in client.get(f"/v1/workspaces/{workspace_id}/members").json()["items"]
    )
    assert roles == ["member", "owner"]


def test_an_invitation_works_once_and_only_for_its_address(client: TestClient) -> None:
    sign_up(client)
    workspace_id = studio(client)
    invited_email = new_email()
    token = client.post(
        f"/v1/workspaces/{workspace_id}/invitations", json={"email": invited_email}
    ).json()["token"]

    sign_up(client)  # someone else
    wrong = client.post("/v1/invitations/accept", json={"token": token})
    assert wrong.json()["error"]["code"] == "invitation_for_another_email"

    sign_up(client, invited_email)
    assert client.post("/v1/invitations/accept", json={"token": token}).status_code == 200
    again = client.post("/v1/invitations/accept", json={"token": token})
    assert again.json()["error"]["code"] == "invitation_not_found"


def test_members_cannot_manage_and_admins_cannot_touch_owners(client: TestClient) -> None:
    owner = sign_up(client)
    workspace_id = studio(client)
    owner_id = user_id(client, owner)
    admin = invite_and_join(client, owner, workspace_id, "admin")
    member = invite_and_join(client, owner, workspace_id, "member")
    member_id = user_id(client, member)

    act_as(client, member)
    for response in [
        client.patch(f"/v1/workspaces/{workspace_id}", json={"name": "No"}),
        client.post(f"/v1/workspaces/{workspace_id}/invitations", json={"email": new_email()}),
        client.get(f"/v1/workspaces/{workspace_id}/invitations"),
    ]:
        assert response.status_code == 403
        assert response.json()["error"] == {
            "code": "role_required",
            "message": "This needs the admin role in the workspace.",
            "detail": {"required": "admin", "role": "member"},
        }

    act_as(client, admin)
    promote = client.patch(
        f"/v1/workspaces/{workspace_id}/members/{member_id}", json={"role": "admin"}
    )
    assert promote.json()["role"] == "admin"
    for response in [
        client.patch(f"/v1/workspaces/{workspace_id}/members/{member_id}", json={"role": "owner"}),
        client.delete(f"/v1/workspaces/{workspace_id}/members/{owner_id}"),
        client.post(
            f"/v1/workspaces/{workspace_id}/invitations",
            json={"email": new_email(), "role": "owner"},
        ),
    ]:
        assert response.status_code == 403
        assert response.json()["error"]["detail"]["required"] == "owner"
    assert client.delete(f"/v1/workspaces/{workspace_id}/members/{member_id}").status_code == 204


def test_a_workspace_keeps_an_owner(client: TestClient) -> None:
    owner = sign_up(client)
    workspace_id = studio(client)
    owner_id = user_id(client, owner)
    personal = client.get("/v1/workspaces").json()["items"]
    personal_id = next(w["id"] for w in personal if w["kind"] == "personal")

    leave = client.delete(f"/v1/workspaces/{workspace_id}/members/{owner_id}")
    demote = client.patch(
        f"/v1/workspaces/{workspace_id}/members/{owner_id}", json={"role": "admin"}
    )
    leave_personal = client.delete(f"/v1/workspaces/{personal_id}/members/{owner_id}")
    for response in (leave, demote, leave_personal):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "last_owner"

    other = invite_and_join(client, owner, workspace_id, "owner")
    act_as(client, owner)
    assert client.delete(f"/v1/workspaces/{workspace_id}/members/{owner_id}").status_code == 204
    act_as(client, other)
    assert client.get(f"/v1/workspaces/{workspace_id}").json()["role"] == "owner"


def test_a_personal_workspace_takes_no_invitations(client: TestClient) -> None:
    sign_up(client)
    personal_id = client.get("/v1/workspaces").json()["items"][0]["id"]
    response = client.post(f"/v1/workspaces/{personal_id}/invitations", json={"email": new_email()})
    assert response.json()["error"]["code"] == "personal_workspace"


def test_workspaces_are_listed_in_pages(client: TestClient) -> None:
    sign_up(client)
    created = {studio(client, f"Studio {n}") for n in range(3)}
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/v1/workspaces", params=params).json()
        seen += [w["id"] for w in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 4
    assert created <= set(seen)


def test_two_users_can_use_the_same_idempotency_key(client: TestClient) -> None:
    sign_up(client)
    headers = {"Idempotency-Key": "same-key"}
    made = client.post("/v1/workspaces", json={"name": "Shared name"}, headers=headers)
    replayed = client.post("/v1/workspaces", json={"name": "Shared name"}, headers=headers)
    assert replayed.json() == made.json()
    assert replayed.headers["Idempotent-Replayed"] == "true"

    sign_up(client)
    theirs = client.post("/v1/workspaces", json={"name": "Shared name"}, headers=headers)
    assert theirs.status_code == 201
    assert "Idempotent-Replayed" not in theirs.headers
    assert theirs.json()["id"] != made.json()["id"]


def test_switching_accounts_with_an_idempotency_key_still_sets_the_cookie(
    client: TestClient,
) -> None:
    other_email = new_email()
    sign_up(client, other_email, name="Other")
    client.post("/v1/auth/signout")
    first = sign_up(client)
    switched = client.post(
        "/v1/auth/signin",
        json={"email": other_email, "password": PASSWORD},
        headers={"Idempotency-Key": "switch"},
    )
    assert "set-cookie" in switched.headers
    assert client.get("/v1/me").json()["email"] == other_email
    # Keys do not apply to session routes: a repeat runs again and sets a cookie again.
    act_as(client, first)
    repeat = client.post(
        "/v1/auth/signin",
        json={"email": other_email, "password": PASSWORD},
        headers={"Idempotency-Key": "switch"},
    )
    assert "set-cookie" in repeat.headers
    assert "Idempotent-Replayed" not in repeat.headers

    act_as(client, first)
    client.post("/v1/auth/signout", headers={"Idempotency-Key": "out"})
    assert client.get("/v1/me").status_code == 401


def test_a_new_invitation_replaces_the_old_one(client: TestClient) -> None:
    sign_up(client)
    workspace_id = studio(client)
    email = new_email()
    path = f"/v1/workspaces/{workspace_id}/invitations"
    old = client.post(path, json={"email": email, "role": "member"}).json()
    new = client.post(path, json={"email": email, "role": "admin"}).json()
    pending = client.get(path).json()["items"]
    assert [(i["id"], i["role"]) for i in pending] == [(new["id"], "admin")]

    sign_up(client, email)
    stale = client.post("/v1/invitations/accept", json={"token": old["token"]})
    assert stale.json()["error"]["code"] == "invitation_not_found"
    assert client.post("/v1/invitations/accept", json={"token": new["token"]}).json()["role"] == (
        "admin"
    )


def test_accepting_when_already_a_member_is_refused(client: TestClient, settings: Settings) -> None:
    owner = sign_up(client)
    workspace_id = studio(client)
    email = new_email()
    token = client.post(
        f"/v1/workspaces/{workspace_id}/invitations", json={"email": email, "role": "admin"}
    ).json()["token"]
    member = sign_up(client, email)
    # They became a member some other way meanwhile (a race with another invitation).
    engine = sync_engine(settings)
    with engine.begin() as conn:
        conn.execute(
            insert(memberships).values(
                workspace_id=workspace_id, user_id=user_id(client, member), role="member"
            )
        )
    engine.dispose()

    act_as(client, member)
    for _ in range(2):  # nothing changes, so a retry gets the same answer
        refused = client.post("/v1/invitations/accept", json={"token": token})
        assert refused.json()["error"]["code"] == "already_member"
    assert client.get(f"/v1/workspaces/{workspace_id}").json()["role"] == "member"
    act_as(client, owner)
    pending = client.get(f"/v1/workspaces/{workspace_id}/invitations").json()["items"]
    assert [i["email"] for i in pending] == [email]


def test_an_invitation_stops_working_when_its_inviter_loses_the_role(
    client: TestClient,
) -> None:
    first_owner = sign_up(client)
    workspace_id = studio(client)
    second_owner = invite_and_join(client, first_owner, workspace_id, "owner")
    second_id = user_id(client, second_owner)
    email = new_email()
    token = client.post(
        f"/v1/workspaces/{workspace_id}/invitations", json={"email": email, "role": "owner"}
    ).json()["token"]

    act_as(client, first_owner)
    demoted = client.patch(
        f"/v1/workspaces/{workspace_id}/members/{second_id}", json={"role": "admin"}
    )
    assert demoted.status_code == 200

    sign_up(client, email)
    refused = client.post("/v1/invitations/accept", json={"token": token})
    assert refused.json()["error"]["code"] == "invitation_not_found"


def test_the_callers_role_is_read_again_under_the_lock(
    client: TestClient, settings: Settings
) -> None:
    owner = sign_up(client)
    workspace_id = studio(client)
    invite_and_join(client, owner, workspace_id)  # leaves the client signed in as them
    me = client.get("/v1/me").json()
    # As if the request was let in as an owner just before a demotion committed.
    stale = WorkspaceAccess(
        CurrentUser(me["id"], me["email"], me["name"], me["language"]),
        workspace_id,
        "Studio",
        "studio",
        "owner",
    )

    async def fresh_role() -> str:
        engine = async_engine(settings)
        try:
            async with engine.begin() as conn:
                return (await workspaces_module._lock(conn, stale)).role
        finally:
            await engine.dispose()

    assert asyncio.run(fresh_role()) == "member"
