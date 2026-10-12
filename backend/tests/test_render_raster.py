"""Chromium draws the SVG (T-12b). Needs Chromium: run with FRAMEGEN_TEST_CHROMIUM=1 (CI
installs it with `playwright install`)."""

import asyncio
import io
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from PIL import Image

from framegen.render import check
from framegen.render.raster import MAX_SIDE, Rasteriser
from framegen.render.svg import render_svg
from framegen.spec import read_spec

pytestmark = pytest.mark.skipif(
    not os.environ.get("FRAMEGEN_TEST_CHROMIUM"), reason="set FRAMEGEN_TEST_CHROMIUM=1"
)


def rasterise(*jobs: tuple[str, int, int]) -> list[bytes]:
    async def run() -> list[bytes]:
        async with Rasteriser() as rasteriser:
            return [await rasteriser.png(svg, width, height) for svg, width, height in jobs]

    return asyncio.run(run())


def alpha(png: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(png))
    assert image.mode == "RGBA"
    return image.getchannel("A")


def frame(shape: str, **window: Any) -> str:
    inset = {"top": 0.05, "bottom": 0.2, "start": 0.06, "end": 0.06}
    spec = read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": shape, **window, "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
    })  # fmt: skip
    return render_svg(spec, "portrait", 600, 900)


def test_the_render_check_passes() -> None:
    assert check.problems(asyncio.run(check.render_test_frame())) == []


@pytest.mark.parametrize(("shape", "window"), [("rectangle", {}), ("rounded", {"radius": 0.1}),
                                               ("oval", {}), ("arch", {})])  # fmt: skip
def test_every_window_shape_cuts_to_exactly_transparent(shape: str, window: dict[str, Any]) -> None:
    (png,) = rasterise((frame(shape, **window), 600, 900))
    channel = alpha(png)
    assert Image.open(io.BytesIO(png)).size == (600, 900)
    histogram = channel.histogram()
    assert sum(histogram[1:255]) == 0, "no pixel is partly transparent"
    assert histogram[0] > 0 and histogram[255] > 0
    assert channel.getpixel((300, 300)) == 0  # inside the window
    assert channel.getpixel((300, 850)) == 255  # under it


def test_the_same_svg_gives_the_same_pixels() -> None:
    svg = frame("rounded", radius=0.13)
    first, second = rasterise((svg, 600, 900), (svg, 600, 900))
    assert Image.open(io.BytesIO(first)).tobytes() == Image.open(io.BytesIO(second)).tobytes()


def test_the_background_is_transparent() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30"></svg>'
    (png,) = rasterise((svg, 40, 30))
    assert alpha(png).getextrema() == (0, 0)


class _Counter(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:
        type(self).hits += 1
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[HTTPServer]:
    httpd = HTTPServer(("127.0.0.1", 0), _Counter)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_nothing_is_loaded_from_the_network(server: HTTPServer) -> None:
    url = f"http://127.0.0.1:{server.server_address[1]}/x.png"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        f'<image href="{url}" width="10" height="10"/></svg>'
    )
    rasterise((svg, 10, 10))
    assert _Counter.hits == 0


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, MAX_SIDE + 1)])
def test_the_size_is_checked(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="each side"):
        rasterise(("<svg/>", width, height))
