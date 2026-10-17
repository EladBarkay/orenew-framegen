"""Text in the frame (DESIGN.md 4.3): the fonts, embedded in the SVG, and the slots text
is drawn in.

Chromium shapes and lays out the text, so every script, right-to-left text and mixed
Hebrew/English work; the fonts are embedded, so it never uses the machine's fonts for
text the font covers. The same files measure the text, to fit it (render.measure).
"""

import base64
import functools
import hashlib
import unicodedata
from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from framegen.fonts import BUILT_IN, BuiltInFont
from framegen.render.measure import Fallback, Measure, Measurer
from framegen.spec.text import Slot

FontFormat = Literal["truetype", "opentype"]

_SIGNATURES: dict[bytes, FontFormat] = {
    b"\x00\x01\x00\x00": "truetype",
    b"true": "truetype",
    b"OTTO": "opentype",
}

_MIME: dict[FontFormat, str] = {"truetype": "font/ttf", "opentype": "font/otf"}


@dataclass(frozen=True)
class FontFile:
    """A workspace font as the renderer is given it: a TrueType or OpenType file. WOFF2
    uploads are unpacked to one when they arrive (T-15), under a size limit, so the
    renderer never decompresses what a user sent."""

    data: bytes

    @property
    def format(self) -> FontFormat:
        try:
            return _SIGNATURES[self.data[:4]]
        except KeyError:
            raise ValueError("a font must be a TrueType or OpenType file") from None

    def __post_init__(self) -> None:
        self.format  # noqa: B018 (checks the signature)


class MissingFont(ValueError):
    pass


class NoRoom(ValueError):
    """The frame leaves a slot no room at all (for example a window reaching the edge)."""


FALLBACK = "heebo"
"""For characters a font does not have (Hebrew in a Latin font): drawn and measured."""


@functools.cache
def _built_in_measure(path: Path, weight: int) -> Measure:
    return Measure(path.read_bytes(), weight)


_WORKSPACE_MEASURES: OrderedDict[bytes, Measure] = OrderedDict()
WORKSPACE_MEASURES_KEPT = 8


def _workspace_measure(data: bytes) -> Measure:
    """Measured at weight 400, as drawn (Fonts.use). The last few are kept, by the file's
    digest, so a job rendering several sizes measures its fonts once."""
    key = hashlib.sha256(data).digest()
    if key in _WORKSPACE_MEASURES:
        _WORKSPACE_MEASURES.move_to_end(key)
    else:
        _WORKSPACE_MEASURES[key] = Measure(data, 400)
        if len(_WORKSPACE_MEASURES) > WORKSPACE_MEASURES_KEPT:
            _WORKSPACE_MEASURES.popitem(last=False)
    return _WORKSPACE_MEASURES[key]


@functools.cache
def _built_in(path: Path) -> tuple[FontFormat, str]:
    """A built-in file's format and base64 text, encoded once per process."""
    file = FontFile(path.read_bytes())
    return file.format, base64.b64encode(file.data).decode("ascii")


def _family(font: BuiltInFont) -> str:
    # One family per folder: a static family's weights are separate faces of it.
    return "fg-" + font.file.split("/")[0]


@dataclass(frozen=True)
class FontUse:
    family: str
    weight: int
    measure: Measurer = field(compare=False, repr=False)


class Fonts:
    """The fonts one SVG uses. Each file is embedded once, however many weights use it."""

    def __init__(self, workspace: Mapping[str, FontFile]) -> None:
        self._workspace = workspace
        self._faces: dict[str, str] = {}

    def use(self, ref: str, text: str = "") -> FontUse:
        """The font for `text`, with the fallback font added if it lacks some of it."""
        use = self._use(ref)
        first = use.measure
        assert isinstance(first, Measure)
        if first.has(text):
            return use
        if use.family == _family(BUILT_IN[FALLBACK]):
            # The font is the fallback: what it lacks is measured as missing.
            return FontUse(use.family, use.weight, Fallback(first, first))
        fallback = self._use(FALLBACK)
        assert isinstance(fallback.measure, Measure)
        # The weight given is the font's: Heebo is variable, so it follows it.
        second = _built_in_measure(BUILT_IN[FALLBACK].path, use.weight)
        return FontUse(f"{use.family}, {fallback.family}", use.weight, Fallback(first, second))

    def _use(self, ref: str) -> FontUse:
        if ref.startswith("font_"):
            try:
                file = self._workspace[ref]
            except KeyError:
                raise MissingFont(f"no font file given for {ref}") from None
            # Each workspace font is its own family, whatever weight its file is.
            use = FontUse(f"fg-{ref}", 400, _workspace_measure(file.data))
            weights = "400"
            if self._face_missing(use, weights):
                self._add(use, weights, file.format, base64.b64encode(file.data).decode("ascii"))
            return use
        try:
            font = BUILT_IN[ref]
        except KeyError:
            raise MissingFont(f"there is no built-in font named {ref}") from None
        measure = _built_in_measure(font.path, font.weight)
        use = FontUse(_family(font), font.weight, measure)
        weights = "1 1000" if font.variable else str(font.weight)
        if self._face_missing(use, weights):
            self._add(use, weights, *_built_in(font.path))
        return use

    def _face_missing(self, use: FontUse, weights: str) -> bool:
        return f"{use.family} {weights}" not in self._faces

    def _add(self, use: FontUse, weights: str, fmt: FontFormat, data: str) -> None:
        self._faces[f"{use.family} {weights}"] = (
            f'@font-face{{font-family:"{use.family}";font-weight:{weights};'
            f'src:url(data:{_MIME[fmt]};base64,{data}) format("{fmt}")}}'
        )

    def style(self) -> str | None:
        if not self._faces:
            return None
        return "<style>" + "".join(self._faces.values()) + "</style>"


def text_direction(text: str, default: Literal["rtl", "ltr"]) -> Literal["rtl", "ltr"]:
    """The direction of the first strong character, as the Unicode paragraph rule (P2)
    says: characters inside an isolate do not count."""
    depth = 0
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in ("LRI", "RLI", "FSI"):
            depth += 1
        elif kind == "PDI":
            depth = max(depth - 1, 0)
        elif depth == 0 and kind in ("R", "AL"):
            return "rtl"
        elif depth == 0 and kind == "L":
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
    def centre(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    @property
    def length(self) -> float:
        """Room along the line."""
        return self.width if self.upright else self.height

    @property
    def depth(self) -> float:
        """Room across the line."""
        return self.height if self.upright else self.width

    def split(self, first: float, gap: float) -> tuple["Area", "Area"]:
        """Into a first part (a share `first` of the depth, less the gap) and the rest
        after the gap, in reading order: below for upright text, to the right for text
        running up."""
        cut = self.depth * first
        if cut - gap / 2 < 1 or self.depth - cut - gap / 2 < 1:
            raise NoRoom("the slot has no room for a second line under the headline")
        if self.upright:
            return (
                Area(self.x, self.y, self.width, cut - gap / 2, True),
                Area(self.x, self.y + cut + gap / 2, self.width, self.height - cut - gap / 2, True),
            )
        return (
            Area(self.x, self.y, cut - gap / 2, self.height, False),
            Area(self.x + cut + gap / 2, self.y, self.width - cut - gap / 2, self.height, False),
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
    taken: Collection[Slot] = (),
) -> Area:
    """A slot's area in a frame of width x height pixels with its window at (x, y, width,
    height). A band's corners are its outer quarters: when another component is in one
    of them (`taken`), the band keeps its middle half, so its text stays centred.
    'under-headline' is part of the headline's slot (see Area.split)."""
    wx, wy, ww, wh = window
    quarter = width / 4
    top = (0.0, wy)
    bottom = (wy + wh, height - wy - wh)
    areas = {
        "top-left": Area(0, top[0], quarter, top[1], True),
        "top-right": Area(width - quarter, top[0], quarter, top[1], True),
        "bottom-left": Area(0, bottom[0], quarter, bottom[1], True),
        "bottom-right": Area(width - quarter, bottom[0], quarter, bottom[1], True),
        "left-edge": Area(0, wy, wx, wh, False),
        "right-edge": Area(wx + ww, wy, width - wx - ww, wh, False),
    }
    for band, (y, depth) in (("top", top), ("bottom", bottom)):
        corners = {f"{band}-start", f"{band}-end"}
        x, length = (quarter, width / 2) if corners & set(taken) else (0, width)
        areas[f"{band}-band"] = Area(x, y, length, depth, True)
    start, end = ("right", "left") if rtl else ("left", "right")
    name = slot.replace("start", start).replace("end", end)
    if name not in areas:
        raise ValueError(f"{slot} is not a slot of its own")
    area = areas[name]
    margin = MARGIN * min(width, height)
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
