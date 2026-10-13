"""Measuring text with the same font files Chromium draws it with (T-13b).

HarfBuzz is the shaper inside Chromium, so the widths here are the widths on the page.
Characters a font does not have are drawn in a fallback font the SVG names and embeds
(render.text), and measured in it (Fallback). Characters neither has (emoji, for
example) are drawn in whatever font the machine has, so they are counted as a square.
"""

import itertools
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import uharfbuzz as hb


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
    """One TrueType or OpenType file at one weight (the weight matters only to a
    variable font). Optical size is left at the font's default, as the SVG asks
    Chromium to (font-optical-sizing:none)."""

    def __init__(self, data: bytes, weight: int) -> None:
        face = hb.Face(hb.Blob(data))
        self._upem: int = face.upem
        self._font = hb.Font(face)
        if any(axis.tag == "wght" for axis in face.axis_infos):
            # As Chromium sets it from the font-weight the SVG gives.
            self._font.set_variations({"wght": weight})
        extents = self._font.get_font_extents("ltr")
        self.line = LineBox(extents.ascender / self._upem, -extents.descender / self._upem)

    def has(self, cluster: str) -> bool:
        """Whether the font draws every character of a cluster (as the shaper maps
        them). Format and control characters draw nothing, so they need no font."""
        return all(
            self._font.get_nominal_glyph(ord(char)) is not None
            or unicodedata.category(char) in ("Cf", "Cc")
            for char in cluster
        )

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

    MISSING = 1.0
    """The width, per pixel of font size, of a character neither font has."""

    def __init__(self, first: Measure, second: Measure) -> None:
        self._first = first
        self._second = second
        self.line = LineBox(
            max(first.line.ascent, second.line.ascent),
            max(first.line.descent, second.line.descent),
        )

    def width(self, text: str) -> float:
        # Chromium picks a font for each whole cluster: a letter with its marks.
        def font(cluster: str) -> Measure | None:
            for measure in (self._first, self._second):
                if measure.has(cluster):
                    return measure
            return None

        total = 0.0
        for measure, run in itertools.groupby(_clusters(text), key=font):
            clusters = list(run)
            if measure is None:
                total += self.MISSING * len(clusters)
            else:
                total += measure.width("".join(clusters))
        return total


def _clusters(text: str) -> Iterator[str]:
    """Each character with the marks and joiners that follow it."""
    cluster = ""
    for char in text:
        if cluster and (unicodedata.category(char).startswith("M") or char == "\u200d"):
            cluster += char
        else:
            if cluster:
                yield cluster
            cluster = char
    if cluster:
        yield cluster


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
