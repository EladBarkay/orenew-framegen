"""Text in the frame (DESIGN.md 4.3): the fonts, embedded in the SVG, and the slots text
is drawn in.

Chromium shapes and lays out the text, so every script, right-to-left text and mixed
Hebrew/English work; the fonts are embedded, so it never uses the machine's fonts for
text the font covers. Fitting text to its slot comes with T-13b.
"""

import base64
import functools
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from framegen.fonts import BUILT_IN
from framegen.spec.text import Slot

FontFormat = Literal["truetype", "opentype", "woff2"]

_SIGNATURES: dict[bytes, FontFormat] = {
    b"\x00\x01\x00\x00": "truetype",
    b"true": "truetype",
    b"OTTO": "opentype",
    b"wOF2": "woff2",
}

_MIME: dict[FontFormat, str] = {
    "truetype": "font/ttf",
    "opentype": "font/otf",
    "woff2": "font/woff2",
}


@dataclass(frozen=True)
class FontFile:
    """A workspace font as the renderer is given it: the file's bytes, as uploaded."""

    data: bytes

    @property
    def format(self) -> FontFormat:
        try:
            return _SIGNATURES[self.data[:4]]
        except KeyError:
            raise ValueError("a font must be a TrueType, OpenType or WOFF2 file") from None

    def __post_init__(self) -> None:
        self.format  # noqa: B018 (checks the signature)


class MissingFont(ValueError):
    pass


class NoRoom(ValueError):
    """The frame leaves a slot no room at all (for example a window reaching the edge)."""


@functools.cache
def _built_in_file(path: Path) -> FontFile:
    return FontFile(path.read_bytes())


@dataclass(frozen=True)
class FontUse:
    family: str
    weight: int


class Fonts:
    """The fonts one SVG uses. Each file is embedded once, however many weights use it."""

    def __init__(self, workspace: Mapping[str, FontFile]) -> None:
        self._workspace = workspace
        self._faces: dict[str, str] = {}

    def use(self, ref: str) -> FontUse:
        if ref.startswith("font_"):
            try:
                file = self._workspace[ref]
            except KeyError:
                raise MissingFont(f"no font file given for {ref}") from None
            family, weights = f"fg-{ref}", "400"
            use = FontUse(family, 400)
        else:
            font = BUILT_IN[ref]
            file = _built_in_file(font.path)
            # One family per folder: a static family's weights are separate faces of it.
            family = "fg-" + font.file.split("/")[0]
            weights = "1 1000" if font.variable else str(font.weight)
            use = FontUse(family, font.weight)
        key = f"{family} {weights}"
        if key not in self._faces:
            data = base64.b64encode(file.data).decode("ascii")
            self._faces[key] = (
                f'@font-face{{font-family:"{family}";font-weight:{weights};'
                f'src:url(data:{_MIME[file.format]};base64,{data}) format("{file.format}")}}'
            )
        return use

    def style(self) -> str | None:
        if not self._faces:
            return None
        return "<style>" + "".join(self._faces.values()) + "</style>"


def text_direction(text: str, default: Literal["rtl", "ltr"]) -> Literal["rtl", "ltr"]:
    """The direction of the first strong character, as the Unicode paragraph rule says."""
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return "rtl"
        if kind == "L":
            return "ltr"
    return default


@dataclass(frozen=True)
class Area:
    """Where a text goes, in pixels. Upright text runs along x; other text runs up the
    frame (turned 90 degrees anticlockwise), as on the owner's stamps."""

    x: float
    y: float
    width: float
    height: float
    upright: bool

    @property
    def length(self) -> float:
        """Room along the line."""
        return self.width if self.upright else self.height

    @property
    def depth(self) -> float:
        """Room across the line."""
        return self.height if self.upright else self.width

    def split(self, first: float) -> tuple["Area", "Area"]:
        """Into a first part (a share `first` of the depth) and the rest after it, in
        reading order: below for upright text, to the right for text running up."""
        if self.upright:
            cut = self.height * first
            return (
                Area(self.x, self.y, self.width, cut, True),
                Area(self.x, self.y + cut, self.width, self.height - cut, True),
            )
        cut = self.width * first
        return (
            Area(self.x, self.y, cut, self.height, False),
            Area(self.x + cut, self.y, self.width - cut, self.height, False),
        )


MARGIN = 0.02
"""Between a slot and the frame's edge or the window, as a share of the shorter side."""

HEADLINE_SHARE = 0.6
"""Of its slot's depth, when another component sits under the headline."""


def slot_area(
    slot: Slot,
    width: int,
    height: int,
    window: tuple[float, float, float, float],
    rtl: bool,
) -> Area:
    """A slot's area in a frame of width x height pixels with its window at (x, y, width,
    height). 'under-headline' is part of the headline's slot (see Area.split)."""
    wx, wy, ww, wh = window
    margin = MARGIN * min(width, height)
    left_side = Area(0, wy, wx, wh, False)
    right_side = Area(wx + ww, wy, width - wx - ww, wh, False)
    top = Area(0, 0, width, wy, True)
    bottom = Area(0, wy + wh, width, height - wy - wh, True)
    third = width / 3
    areas = {
        "top-band": top,
        "bottom-band": bottom,
        "top-left": Area(0, 0, third, wy, True),
        "top-right": Area(width - third, 0, third, wy, True),
        "bottom-left": Area(0, wy + wh, third, bottom.height, True),
        "bottom-right": Area(width - third, wy + wh, third, bottom.height, True),
        "left-edge": left_side,
        "right-edge": right_side,
    }
    start, end = ("right", "left") if rtl else ("left", "right")
    name = slot.replace("start", start).replace("end", end)
    if name not in areas:
        raise ValueError(f"{slot} is not a slot of its own")
    area = areas[name]
    inner = Area(
        area.x + margin,
        area.y + margin,
        area.width - 2 * margin,
        area.height - 2 * margin,
        area.upright,
    )
    if inner.width < 1 or inner.height < 1:
        raise NoRoom(f"the frame leaves no room for the {slot} slot at {width}x{height}")
    return inner
