"""Uploads through pre-signed links, against a real Postgres and S3 storage (RustFS)."""

import hashlib
import io
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from framegen.api.app import create_app
from framegen.settings import Settings
from framegen.storage.client import s3_client


@pytest.fixture
def client(storage_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(readiness_checks={}, settings=storage_settings)) as test_client:
        response = test_client.post(
            "/v1/auth/signup",
            json={
                "email": f"u-{uuid.uuid4().hex[:12]}@example.com",
                "password": "correct horse battery",
                "name": "Up",
            },
        )
        assert response.status_code == 201
        yield test_client


def workspace(client: TestClient) -> str:
    found: str = client.get("/v1/workspaces").json()["items"][0]["id"]
    return found


def png(size: tuple[int, int] = (120, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, (0, 0, 0, 0)).save(out, "PNG")
    return out.getvalue()


def start(
    client: TestClient,
    workspace_id: str,
    data: bytes,
    content_type: str = "image/png",
    filename: str = "frame.png",
    kind: str = "reference",
) -> Any:
    return client.post(
        f"/v1/workspaces/{workspace_id}/assets",
        json={
            "kind": kind,
            "filename": filename,
            "content_type": content_type,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )


@dataclass
class Fetched:
    status_code: int
    headers: dict[str, str]
    content: bytes


def fetch(url: str, method: str = "GET", data: bytes | None = None, **headers: str) -> Fetched:
    """Straight to storage, as a browser would (not through the API)."""
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as answer:
            return Fetched(
                answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
            )
    except urllib.error.HTTPError as error:
        return Fetched(error.code, {}, error.read())


def upload(created: dict[str, Any], data: bytes) -> Fetched:
    target = created["upload"]
    return fetch(target["url"], target["method"], data, **target["headers"])


def test_upload_complete_and_download(client: TestClient) -> None:
    workspace_id = workspace(client)
    data = png()
    created = start(client, workspace_id, data).json()
    assert created["asset"]["status"] == "pending"
    assert created["asset"]["download_url"] is None
    assert upload(created, data).status_code == 200

    asset_id = created["asset"]["id"]
    done = client.post(f"/v1/workspaces/{workspace_id}/assets/{asset_id}/complete").json()
    assert (done["status"], done["width"], done["height"]) == ("ready", 120, 80)
    assert done["sha256"] == hashlib.sha256(data).hexdigest()

    download = fetch(done["download_url"])
    assert download.content == data
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"frame.png\"; filename*=UTF-8''frame.png"
    )

    again = client.post(f"/v1/workspaces/{workspace_id}/assets/{asset_id}/complete")
    assert again.json()["status"] == "ready"
    listed = client.get(f"/v1/workspaces/{workspace_id}/assets").json()["items"]
    assert [a["id"] for a in listed] == [asset_id]


def test_storage_refuses_other_content_or_size_than_declared(client: TestClient) -> None:
    workspace_id = workspace(client)
    created = start(client, workspace_id, png()).json()
    assert upload(created, png((121, 80))).status_code == 400

    data = png()
    declared = {
        "kind": "reference",
        "filename": "frame.png",
        "content_type": "image/png",
        "size": 10,  # smaller than the file, which has the declared checksum
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    too_small = client.post(f"/v1/workspaces/{workspace_id}/assets", json=declared).json()
    assert upload(too_small, data).status_code == 403


def test_completing_before_uploading(client: TestClient) -> None:
    workspace_id = workspace(client)
    created = start(client, workspace_id, png()).json()
    response = client.post(
        f"/v1/workspaces/{workspace_id}/assets/{created['asset']['id']}/complete"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload_missing"


def test_a_file_that_is_not_its_declared_type_is_removed(
    client: TestClient, storage_settings: Settings
) -> None:
    workspace_id = workspace(client)
    page = b"<!doctype html><script>alert(document.cookie)</script>"
    created = start(client, workspace_id, page).json()
    assert upload(created, page).status_code == 200
    asset_id = created["asset"]["id"]
    response = client.post(f"/v1/workspaces/{workspace_id}/assets/{asset_id}/complete")
    assert response.json()["error"]["code"] == "not_the_declared_type"
    assert client.get(f"/v1/workspaces/{workspace_id}/assets/{asset_id}").status_code == 404
    storage = s3_client(storage_settings)
    listed = storage.list_objects_v2(
        Bucket=storage_settings.s3_bucket, Prefix=f"workspaces/{workspace_id}/assets/{asset_id}"
    )
    assert listed.get("KeyCount") == 0


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"filename": "frame.jpg"}, "extension_does_not_match_type"),
        ({"kind": "font"}, "kind_does_not_match_type"),
        ({"size": 3 * 1024**3}, "file_too_large"),
    ],
)
def test_bad_declarations_are_refused(client: TestClient, body: dict[str, Any], code: str) -> None:
    declared = {
        "kind": "reference",
        "filename": "frame.png",
        "content_type": "image/png",
        "size": 10,
        "sha256": "0" * 64,
    }
    response = client.post(f"/v1/workspaces/{workspace(client)}/assets", json=declared | body)
    assert response.json()["error"]["code"] == code


def test_another_workspace_cannot_see_an_asset(client: TestClient) -> None:
    workspace_id = workspace(client)
    data = png()
    created = start(client, workspace_id, data).json()
    upload(created, data)
    asset_id = created["asset"]["id"]
    client.post(f"/v1/workspaces/{workspace_id}/assets/{asset_id}/complete")

    client.cookies.clear()
    client.post(
        "/v1/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:12]}@example.com",
            "password": "correct horse battery",
            "name": "Other",
        },
    )
    mine = workspace(client)
    assert client.get(f"/v1/workspaces/{workspace_id}/assets/{asset_id}").status_code == 404
    assert client.get(f"/v1/workspaces/{mine}/assets/{asset_id}").status_code == 404
    assert client.get(f"/v1/workspaces/{mine}/assets").json()["items"] == []


def test_fonts_and_kind_filter(client: TestClient) -> None:
    workspace_id = workspace(client)
    font = b"OTTO" + b"\0" * 200
    created = start(client, workspace_id, font, "font/otf", "Heebo.otf", "font").json()
    upload(created, font)
    done = client.post(
        f"/v1/workspaces/{workspace_id}/assets/{created['asset']['id']}/complete"
    ).json()
    assert (done["kind"], done["width"]) == ("font", None)
    fonts = client.get(f"/v1/workspaces/{workspace_id}/assets", params={"kind": "font"})
    assert [a["id"] for a in fonts.json()["items"]] == [done["id"]]
    references = client.get(f"/v1/workspaces/{workspace_id}/assets", params={"kind": "reference"})
    assert references.json()["items"] == []


def test_a_hebrew_file_name_downloads_under_its_name(client: TestClient) -> None:
    workspace_id = workspace(client)
    data = png()
    created = start(client, workspace_id, data, filename="מסגרת.png").json()
    upload(created, data)
    done = client.post(
        f"/v1/workspaces/{workspace_id}/assets/{created['asset']['id']}/complete"
    ).json()
    disposition = fetch(done["download_url"]).headers["content-disposition"]
    assert "filename*=UTF-8''%D7%9E%D7%A1%D7%92%D7%A8%D7%AA.png" in disposition
