"""The brand kit's storage, API and render inputs (T-15b), against a real Postgres."""

import asyncio
import base64
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from framegen.api.app import create_app
from framegen.brand import FontNotInKit, NoBrandStamp, brand_inputs
from framegen.db.engine import async_engine, sync_engine
from framegen.db.tables import assets, memberships
from framegen.render.svg import Image
from framegen.settings import Settings
from framegen.spec import read_spec
from framegen.spec.text import BrandText

PASSWORD = "correct horse battery"
B32 = "abcdefghijklmnopqrstuvwxyz234567"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(readiness_checks={}, settings=settings)) as test_client:
        sign_up(test_client)
        yield test_client


def sign_up(client: TestClient) -> str:
    client.cookies.clear()
    response = client.post(
        "/v1/auth/signup",
        json={"email": f"b-{uuid.uuid4().hex[:12]}@example.com", "password": PASSWORD,
              "name": "Brand"},
    )  # fmt: skip
    assert response.status_code == 201, response.text
    user_id: str = client.get("/v1/me").json()["id"]
    return user_id


def workspace(client: TestClient) -> str:
    found: str = client.get("/v1/workspaces").json()["items"][0]["id"]
    return found


def upload(settings: Settings, workspace_id: str, **row: Any) -> str:
    """A ready asset, as if uploaded (no storage needed here)."""
    asset_id = "ast_" + "".join(secrets.choice(B32) for _ in range(26))
    values = {
        "id": asset_id, "workspace_id": workspace_id, "kind": "stamp", "status": "ready",
        "storage_key": f"workspaces/{workspace_id}/assets/{asset_id}",
        "filename": "file", "content_type": "image/png", "size": 10, "sha256": "0" * 64,
        "width": 200, "height": 100, "created_at": datetime.now(UTC), **row,
    }  # fmt: skip
    engine = sync_engine(settings)
    with engine.begin() as conn:
        conn.execute(insert(assets).values(**values))
    engine.dispose()
    return asset_id


def kit(version: Any = 0, **content: Any) -> dict[str, Any]:
    return {"version": version, **content}


def put(client: TestClient, workspace_id: str, body: dict[str, Any]) -> Any:
    return client.put(f"/v1/workspaces/{workspace_id}/brand-kit", json=body)


TEXT_STAMP = {"kind": "text", "text": "Orenew\n050-1234567", "font": "amatic-sc-bold",
              "color": "#3a2c12"}  # fmt: skip


def test_an_unsaved_kit_is_empty(client: TestClient) -> None:
    got = client.get(f"/v1/workspaces/{workspace(client)}/brand-kit").json()
    assert got["version"] == 0 and got["stamps"] == [] and got["default_stamp"] is None
    assert got["stamp_placement"] == {"slot": "end-edge", "size": 0.08, "opacity": 1.0}


def test_a_kit_is_saved_and_read_back(client: TestClient, settings: Settings) -> None:
    ws = workspace(client)
    logo, font = upload(settings, ws), upload(settings, ws, kind="font", content_type="font/ttf")
    body = kit(
        stamps=[TEXT_STAMP, {"kind": "image", "asset": logo}],
        default_stamp=1,
        fonts=[{"asset": font, "name": "Flamingo"}],
        colors=[{"color": "#3a2c12", "name": "Brown"}],
        stamp_placement={"slot": "bottom-end", "size": 0.1, "opacity": 0.9},
    )
    saved = put(client, ws, body)
    assert saved.status_code == 200, saved.text
    got = client.get(f"/v1/workspaces/{ws}/brand-kit").json()
    assert got == saved.json()
    assert got["version"] == 1
    assert got["fonts"] == [{"asset": font, "name": "Flamingo", "id": "font_" + font[4:]}]
    assert got["stamps"][1] == {"kind": "image", "asset": logo}


def test_an_edit_from_an_old_version_is_refused(client: TestClient) -> None:
    ws = workspace(client)
    assert put(client, ws, kit(colors=[{"color": "#000000"}])).status_code == 200
    stale = put(client, ws, kit(colors=[{"color": "#ffffff"}]))  # also started from 0
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "brand_kit_changed")
    assert put(client, ws, kit(1, colors=[{"color": "#ffffff"}])).json()["version"] == 2
    assert put(client, ws, kit(1)).status_code == 409


@pytest.mark.parametrize(
    ("row", "code"),
    [({"kind": "reference"}, "stamp_not_found"),
     ({"status": "pending"}, "stamp_not_found"),
     ({"content_type": "image/webp"}, "stamp_format_unsupported"),
     ({"width": 2100, "height": 100}, "stamp_too_thin"),
     ({"width": None, "height": None}, "stamp_size_unknown")],
)  # fmt: skip
def test_a_stamp_image_is_checked(
    client: TestClient, settings: Settings, row: dict[str, Any], code: str
) -> None:
    ws = workspace(client)
    logo = upload(settings, ws, **row)
    answer = put(client, ws, kit(stamps=[{"kind": "image", "asset": logo}]))
    assert (answer.status_code, answer.json()["error"]["code"]) == (422, code)
    assert answer.json()["error"]["detail"] == {"field": "stamps[0].asset"}


@pytest.mark.parametrize(
    ("row", "code"),
    [({"kind": "stamp", "content_type": "font/ttf"}, "font_not_found"),
     ({"kind": "font", "content_type": "font/woff2"}, "font_format_unsupported")],
)  # fmt: skip
def test_a_font_is_checked(
    client: TestClient, settings: Settings, row: dict[str, Any], code: str
) -> None:
    ws = workspace(client)
    font = upload(settings, ws, **row)
    answer = put(client, ws, kit(fonts=[{"asset": font, "name": "F"}]))
    assert (answer.status_code, answer.json()["error"]["code"]) == (422, code)


def test_another_workspaces_upload_is_not_found(client: TestClient, settings: Settings) -> None:
    theirs = workspace(client)
    logo = upload(settings, theirs)
    sign_up(client)
    answer = put(client, workspace(client), kit(stamps=[{"kind": "image", "asset": logo}]))
    assert answer.json()["error"]["code"] == "stamp_not_found"


def test_a_text_stamp_uses_a_built_in_or_kit_font(client: TestClient) -> None:
    ws = workspace(client)
    stamp = {**TEXT_STAMP, "font": "font_" + "a" * 26}
    answer = put(client, ws, kit(stamps=[stamp]))
    assert (answer.status_code, answer.json()["error"]["code"]) == (422, "font_not_in_kit")
    unknown = put(client, ws, kit(stamps=[{**TEXT_STAMP, "font": "comic-sans"}]))
    assert unknown.status_code == 422


def test_the_default_stamp_is_one_of_the_stamps(client: TestClient) -> None:
    answer = put(client, workspace(client), kit(stamps=[TEXT_STAMP], default_stamp=1))
    assert answer.status_code == 422


def test_members_read_the_kit_and_admins_save_it(client: TestClient, settings: Settings) -> None:
    ws = workspace(client)
    member = sign_up(client)
    engine = sync_engine(settings)
    with engine.begin() as conn:
        conn.execute(insert(memberships).values(workspace_id=ws, user_id=member, role="member"))
    engine.dispose()
    assert client.get(f"/v1/workspaces/{ws}/brand-kit").status_code == 200
    answer = put(client, ws, kit())
    assert (answer.status_code, answer.json()["error"]["code"]) == (403, "role_required")


def inputs(settings: Settings, ws: str, spec: dict[str, Any], files: dict[str, bytes]) -> Any:
    async def run() -> Any:
        engine = async_engine(settings)

        async def read(key: str) -> bytes:
            return files[key]

        try:
            async with engine.connect() as conn:
                return await brand_inputs(conn, ws, read_spec(spec), read)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def frame(**parts: Any) -> dict[str, Any]:
    inset = {"top": 0.1, "bottom": 0.2, "start": 0.1, "end": 0.1}
    return {
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
        **parts,
    }  # fmt: skip


def test_the_kits_image_stamp_and_used_fonts_reach_the_renderer(
    client: TestClient, settings: Settings
) -> None:
    ws = workspace(client)
    logo = upload(settings, ws)
    used = upload(settings, ws, kind="font", content_type="font/ttf")
    unused = upload(settings, ws, kind="font", content_type="font/otf")
    body = kit(stamps=[{"kind": "image", "asset": logo}], default_stamp=0,
               fonts=[{"asset": used, "name": "A"}, {"asset": unused, "name": "B"}])  # fmt: skip
    assert put(client, ws, body).status_code == 200
    files = {f"workspaces/{ws}/assets/{logo}": b"\x89PNG-logo",
             f"workspaces/{ws}/assets/{used}": b"\x00\x01\x00\x00font"}  # fmt: skip
    spec = frame(
        headline={"text": "נועה", "font": "font_" + used[4:], "color": "#000000",
                  "size": 0.05, "slot": "bottom-band"},
        stamp={"source": "brand-kit", "slot": "end-edge"},
    )  # fmt: skip
    stamp, fonts = inputs(settings, ws, spec, files)
    assert stamp == Image("data:image/png;base64," + base64.b64encode(b"\x89PNG-logo").decode(),
                          200, 100)  # fmt: skip
    assert list(fonts) == ["font_" + used[4:]]  # only the font the frame uses is read


def test_the_kits_text_stamp_reaches_the_renderer(client: TestClient, settings: Settings) -> None:
    ws = workspace(client)
    assert put(client, ws, kit(stamps=[TEXT_STAMP], default_stamp=0)).status_code == 200
    stamp, fonts = inputs(settings, ws, frame(stamp={"source": "brand-kit", "slot": "top-end"}),
                          {})  # fmt: skip
    assert stamp == BrandText(text=TEXT_STAMP["text"], font="amatic-sc-bold", color="#3a2c12")
    assert fonts == {}


def test_a_frame_using_the_kit_needs_a_default_stamp(
    client: TestClient, settings: Settings
) -> None:
    ws = workspace(client)
    with pytest.raises(NoBrandStamp):
        inputs(settings, ws, frame(stamp={"source": "brand-kit", "slot": "top-end"}), {})
    stamp, _ = inputs(settings, ws, frame(), {})
    assert stamp is None


@pytest.mark.parametrize(
    "body",
    [kit(2**31 - 1), kit("1"), kit(stamps=[TEXT_STAMP, TEXT_STAMP], default_stamp=True),
     kit(stamps=[TEXT_STAMP], default_stamp=0, stamp_placement={"size": 0.3})],
)  # fmt: skip
def test_a_bad_kit_is_refused_before_anything_is_stored(
    client: TestClient, body: dict[str, Any]
) -> None:
    answer = put(client, workspace(client), body)
    assert (answer.status_code, answer.json()["error"]["code"]) == (422, "validation_failed")


def test_a_font_is_in_the_kit_once(client: TestClient, settings: Settings) -> None:
    ws = workspace(client)
    font = upload(settings, ws, kind="font", content_type="font/ttf")
    twice = [{"asset": font, "name": "A"}, {"asset": font, "name": "B"}]
    assert put(client, ws, kit(fonts=twice)).status_code == 422


def test_a_frame_naming_a_font_the_kit_lost_is_a_clear_error(
    client: TestClient, settings: Settings
) -> None:
    ws = workspace(client)
    spec = frame(headline={"text": "נועה", "font": "font_" + "q" * 26, "color": "#000000",
                           "size": 0.05, "slot": "bottom-band"})  # fmt: skip
    with pytest.raises(FontNotInKit, match="font_q"):
        inputs(settings, ws, spec, {})
