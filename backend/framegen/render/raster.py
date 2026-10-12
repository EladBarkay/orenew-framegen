"""Turns a frame's SVG into PNG pixels with headless Chromium (DESIGN.md 9).

Playwright is pinned (pyproject.toml), and with it the Chromium build, so the same SVG
gives the same pixels. The page loads nothing: no network, and the SVG's images are
data: URLs (render.svg checks that).
"""

import asyncio
from types import TracebackType
from typing import Self

from playwright.async_api import Browser, Playwright, Route, async_playwright

MAX_SIDE = 16384
"""Chromium's largest screenshot side. Print sizes at 300 dpi stay well under it."""

MAX_PIXELS = 80_000_000
"""Enough for a 60x90 cm poster at 300 dpi; more would risk the worker's memory."""

TIMEOUT_S = 120
"""For everything one frame takes: the largest take tens of seconds."""

LAUNCH_ARGS = [
    # The same pixels on every machine: no GPU, a fixed colour profile, no LCD
    # subpixel text and no hinting (text comes with T-13).
    "--disable-gpu",
    "--force-color-profile=srgb",
    "--disable-lcd-text",
    "--font-render-hinting=none",
]


class Rasteriser:
    """One Chromium for many frames. Use as `async with Rasteriser() as r: await r.png(...)`."""

    def __init__(self, executable_path: str | None = None) -> None:
        self._executable_path = executable_path
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        try:
            await self._launch()
        except BaseException:
            await self._playwright.stop()
            raise
        return self

    async def _launch(self) -> Browser:
        assert self._playwright is not None
        self._browser = await self._playwright.chromium.launch(
            executable_path=self._executable_path, args=LAUNCH_ARGS
        )
        return self._browser

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()

    async def png(self, svg: str, width: int, height: int) -> bytes:
        """The SVG drawn at exactly width x height pixels, with a transparent background,
        as an 8-bit RGBA PNG."""
        if self._browser is None:
            raise RuntimeError("use the Rasteriser in 'async with'")
        if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
            raise ValueError(f"each side must be 1 to {MAX_SIDE} pixels, not {width}x{height}")
        if width * height > MAX_PIXELS:
            raise ValueError(f"{width}x{height} is more than {MAX_PIXELS:,} pixels")
        async with asyncio.timeout(TIMEOUT_S):
            return await self._png(svg, width, height)

    async def _png(self, svg: str, width: int, height: int) -> bytes:
        browser = self._browser
        if browser is None or not browser.is_connected():
            # Chromium crashed or was killed: start it again rather than fail every frame.
            browser = await self._launch()
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            offline=True,
            # Nothing on the page needs scripts; text from people will be on it (T-13).
            java_script_enabled=False,
        )
        try:
            page = await context.new_page()
            await page.route("**/*", _refuse)
            await page.set_content(
                "<!doctype html><html><head><style>html,body{margin:0;background:transparent}"
                "svg{display:block}</style></head><body>" + svg + "</body></html>",
                wait_until="load",
            )
            return await page.screenshot(
                type="png",
                omit_background=True,
                clip={"x": 0, "y": 0, "width": width, "height": height},
                animations="disabled",
            )
        finally:
            await context.close()


async def _refuse(route: Route) -> None:
    await route.abort("blockedbyclient")
