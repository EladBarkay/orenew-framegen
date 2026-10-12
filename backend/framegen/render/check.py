"""`framegen-render-check`: draws a test frame in this machine's Chromium and checks the
pixels, so a deployment can show its renderer works (CI runs it in the worker image)."""

import asyncio
import io
import sys

from PIL import Image

from framegen.render.raster import Rasteriser
from framegen.render.svg import render_svg
from framegen.spec import FrameSpec, read_spec

WIDTH, HEIGHT = 600, 900

TEST_FRAME = {
    "specVersion": 1,
    "aspect": {"portrait": "2:3", "landscape": "3:2"},
    "window": {
        "shape": "oval",
        "portrait": {"inset": {"top": 0.05, "bottom": 0.2, "start": 0.06, "end": 0.06}},
        "landscape": {"inset": {"top": 0.06, "bottom": 0.22, "start": 0.05, "end": 0.05}},
    },
    "decoration": {
        "archetype": "bar",
        "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"kind": "vector", "shape": "bar", "edge": "bottom", "distance": 0.25,
             "thickness": 0.05, "color": "#ffffff", "overlapsWindow": True},
        ],
    },
}  # fmt: skip


def problems(png: bytes) -> list[str]:
    """What is wrong with the test frame's pixels, if anything."""
    image = Image.open(io.BytesIO(png))
    found = []
    if image.size != (WIDTH, HEIGHT) or image.mode != "RGBA":
        found.append(f"expected a {WIDTH}x{HEIGHT} RGBA image, got {image.size} {image.mode}")
        return found
    alpha = image.getchannel("A")
    if alpha.getpixel((5, 5)) != 255:
        found.append("the decoration is not opaque")
    if alpha.getpixel((WIDTH // 2, HEIGHT // 3)) != 0:
        found.append("the window is not transparent")
    if alpha.getpixel((WIDTH // 2, round(HEIGHT * 0.725))) != 255:
        found.append("the bar over the window is missing")
    partial = sum(alpha.histogram()[1:255])
    if partial:
        found.append(f"{partial} pixels are partly transparent")
    return found


async def render_test_frame(executable_path: str | None = None) -> bytes:
    spec: FrameSpec = read_spec(TEST_FRAME)
    async with Rasteriser(executable_path) as rasteriser:
        return await rasteriser.png(render_svg(spec, "portrait", WIDTH, HEIGHT), WIDTH, HEIGHT)


def main() -> None:
    found = problems(asyncio.run(render_test_frame()))
    if found:
        sys.exit("render check failed: " + "; ".join(found))
    print("render check: ok")
