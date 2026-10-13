"""Measuring text with the same font files Chromium draws it with (T-13b).

HarfBuzz is the shaper inside Chromium, so the widths here are the widths on the page.
Characters a font does not have are drawn in a fallback font the SVG names and embeds
(render.text), and measured in it (Fallback), so no machine font is left to guess.
"""

import io
import itertools
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import uharfbuzz as hb
from fontTools.ttLib import TTFont


@dataclass(frozen=True)
class LineBox:
    """A font's line, per pixel of font size."""

    ascent: float
    """From the baseline up to the line's top."""
    descent: float
    """From the baseline down to the line's bottom (positive)."""

    @property
    def height(self) -> float:
        return self.ascent + self.descent


class Measurer(Protocol):
    @property
    def line(self) -> LineBox: ...

    def width(self, text: str) -> float: ...


class Measure:
    """One font file at one weight (the weight matters only to a variable font)."""

    def __init__(self, data: bytes, weight: int) -> None:
        if data[:4] == b"wOF2":
            # HarfBuzz reads TrueType and OpenType; WOFF2 is those, compressed.
            try:
                font = TTFont(io.BytesIO(data))
                font.flavor = None
                out = io.BytesIO()
                font.save(out)
            except Exception as error:
                raise ValueError("the WOFF2 font file cannot be read") from error
            data = out.getvalue()
        face = hb.Face(hb.Blob(data))
        self._upem: int = face.upem
        self._unicodes: set[int] = set(face.unicodes)
        self._font = hb.Font(face)
        if any(axis.tag == "wght" for axis in face.axis_infos):
            # As Chromium sets it from the font-weight the SVG gives.
            self._font.set_variations({"wght": weight})
        extents = self._font.get_font_extents("ltr")
        self.line = LineBox(extents.ascender / self._upem, -extents.descender / self._upem)

    def has(self, char: str) -> bool:
        """Whether the font draws the character. Format and control characters draw
        nothing, so they need no font."""
        return ord(char) in self._unicodes or unicodedata.category(char) in ("Cf", "Cc")

    def width(self, text: str) -> float:
        """The text's advance, per pixel of font size."""
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self._font, buffer, {})
        advance: int = sum(position.x_advance for position in buffer.glyph_positions)
        return advance / self._upem


class Fallback:
    """A font with a second one for the characters it does not have, as Chromium draws
    them: each run of characters in the first font that has them."""

    def __init__(self, first: Measure, second: Measure) -> None:
        self._first = first
        self._second = second
        self.line = LineBox(
            max(first.line.ascent, second.line.ascent),
            max(first.line.descent, second.line.descent),
        )

    def width(self, text: str) -> float:
        return sum(
            (self._first if own else self._second).width("".join(run))
            for own, run in itertools.groupby(text, key=self._first.has)
        )


WRAP_BELOW = 0.75
"""A one-line text that would shrink below this share of its size is tried on two
lines, and kept there if that lets it be bigger."""


@dataclass(frozen=True)
class Layout:
    lines: list[str]
    size: float
    """Font size in pixels."""
    baselines: list[float]
    """Each line's baseline, from the middle of its area across the lines (down)."""


def fit(lines: list[str], measure: Measurer, length: float, depth: float, size: float) -> Layout:
    """The lines at the largest size up to `size` pixels at which every line fits within
    `length` and the lines' boxes, stacked, within `depth`. Text is never wider or deeper
    than its area: it shrinks as far as it must."""

    def largest(lines: list[str]) -> float:
        widest = max(measure.width(line) for line in lines)
        return min(
            size,
            length / widest if widest > 0 else size,
            depth / (len(lines) * measure.line.height),
        )

    best = largest(lines)
    if len(lines) == 1 and best < WRAP_BELOW * size:
        wrapped = _two_lines(lines[0], measure)
        wrapped_size = 0.0 if wrapped is None else largest(wrapped)
        if wrapped is not None and wrapped_size > best:
            lines, best = wrapped, wrapped_size
    step = measure.line.height * best
    top = -len(lines) * step / 2
    return Layout(
        lines, best, [top + i * step + measure.line.ascent * best for i in range(len(lines))]
    )


def _two_lines(line: str, measure: Measurer) -> list[str] | None:
    """The line broken at the space that leaves its longer half shortest. Only at
    spaces: a no-break space is there so as not to break."""
    words = line.split(" ")
    splits = [
        [" ".join(words[:i]).rstrip(" "), " ".join(words[i:]).lstrip(" ")]
        for i in range(1, len(words))
    ]
    splits = [split for split in splits if all(split)]
    if not splits:
        return None
    return min(splits, key=lambda split: max(measure.width(part) for part in split))
