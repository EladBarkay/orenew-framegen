"""Chromium draws the SVG (T-12b). Needs Chromium: run with FRAMEGEN_TEST_CHROMIUM=1 (CI
installs it with `playwright install`)."""

import asyncio
import io
import os
import re
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


def frame(shape: str, headline: dict[str, Any] | None = None, **window: Any) -> str:
    inset = {"top": 0.05, "bottom": 0.2, "start": 0.06, "end": 0.06}
    spec = read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": shape, **window, "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
        **({"headline": headline} if headline else {}),
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


def test_the_pixel_count_is_capped() -> None:
    with pytest.raises(ValueError, match="more than"):
        rasterise(("<svg/>", 10_000, 10_000))


def test_a_crashed_chromium_is_started_again() -> None:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"></svg>'

    async def run() -> bytes:
        async with Rasteriser() as rasteriser:
            await rasteriser.png(svg, 20, 20)
            assert rasteriser._browser is not None
            await rasteriser._browser.close()  # as if Chromium had died
            return await rasteriser.png(svg, 20, 20)

    assert alpha(asyncio.run(run())).getextrema() == (0, 0)


def test_a_closed_rasteriser_refuses_frames() -> None:
    async def run() -> None:
        async with Rasteriser() as rasteriser:
            pass
        await rasteriser.png("<svg/>", 10, 10)

    with pytest.raises(RuntimeError, match="async with"):
        asyncio.run(run())


def headline(font: str, text: str = "נועה ועודד", size: float = 0.06) -> dict[str, Any]:
    return {"text": text, "font": font, "color": "#ffffff", "size": size, "slot": "bottom-band"}


def ink(png: bytes) -> Image.Image:
    """The text's pixels: white on the blue decoration."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    return image.getchannel("R").point(lambda red: 255 if red > 0x99 else 0)


def test_text_is_drawn_in_its_embedded_font() -> None:
    fonts = ["heebo-light", "heebo-black", "suez-one", "unknown"]
    svgs = [frame("rectangle", headline("heebo" if f == "unknown" else f)) for f in fonts]
    # A family the page does not have: what Chromium would draw without the embedded font.
    svgs[3] = svgs[3].replace('font-family="fg-heebo"', 'font-family="not-embedded"')
    light, black, suez, fallback = [ink(png) for png in rasterise(*((s, 600, 900) for s in svgs))]
    amounts = [sum(i.histogram()[255:]) for i in (light, black, suez, fallback)]
    assert amounts[0] > 0
    assert amounts[1] > 1.5 * amounts[0], "the variable font's weight is applied"
    images = [light.tobytes(), black.tobytes(), suez.tobytes(), fallback.tobytes()]
    assert len(set(images)) == 4


def test_text_too_big_for_its_slot_stays_out_of_the_window() -> None:
    (png,) = rasterise((frame("rectangle", headline("heebo-black", "נ" * 30, 0.25)), 600, 900))
    # The window is 45 to 720 down and 36 to 564 across.
    window = alpha(png).crop((36, 45, 564, 720))
    assert window.getextrema() == (0, 0)


@pytest.mark.parametrize(
    "font", ["heebo-black", "suez-one", "amatic-sc-bold", "great-vibes", "playfair-display"]
)
def test_long_text_is_fitted_to_its_slot_as_chromium_draws_it(font: str) -> None:
    text = "Noa & Oded נועה ועודד" if font != "great-vibes" else "Noa and Oded forever"
    svg = frame("rectangle", headline(font, text, 0.12))
    (png,) = rasterise((svg, 600, 900))
    box = ink(png).getbbox()
    assert box is not None
    left, top, right, bottom = box
    # The bottom band's area is 12 to 588 across and 732 to 888 down (the window ends at
    # 720, the frame at 900). HarfBuzz's widths are Chromium's: text that had to shrink
    # fills the area's length, give or take the glyphs' side bearings, and stays inside.
    assert left >= 11 and right <= 589
    assert top >= 720 and bottom <= 900
    size = float(re.findall(r'font-size="([\d.]+)"', svg)[0])
    if size < 0.12 * 600:
        assert right - left > 0.85 * 576
