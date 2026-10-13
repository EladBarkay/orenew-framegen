"""Measuring text with the same font files Chromium draws it with (T-13b).

HarfBuzz is the shaper inside Chromium, so the widths here are the widths on the page.
Characters a font does not have are drawn by Chromium in a fallback font, which this
does not know about; they are measured as the font's missing-glyph box.
"""

import io
from dataclasses import dataclass

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


class Measure:
    """One font file at one weight."""

    def __init__(self, data: bytes, weight: int | None) -> None:
        if data[:4] == b"wOF2":
            # HarfBuzz reads TrueType and OpenType; WOFF2 is those, compressed.
            font = TTFont(io.BytesIO(data))
            font.flavor = None
            out = io.BytesIO()
            font.save(out)
            data = out.getvalue()
        face = hb.Face(hb.Blob(data))
        self._upem: int = face.upem
        self._font = hb.Font(face)
        if weight is not None:
            self._font.set_variations({"wght": weight})
        extents = self._font.get_font_extents("ltr")
        self.line = LineBox(extents.ascender / self._upem, -extents.descender / self._upem)

    def width(self, text: str) -> float:
        """The text's advance, per pixel of font size."""
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self._font, buffer, {})
        advance: int = sum(position.x_advance for position in buffer.glyph_positions)
        return advance / self._upem


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


def fit(lines: list[str], measure: Measure, length: float, depth: float, size: float) -> Layout:
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
        if wrapped is not None and largest(wrapped) > best:
            lines, best = wrapped, largest(wrapped)
    step = measure.line.height * best
    top = -len(lines) * step / 2
    return Layout(
        lines, best, [top + i * step + measure.line.ascent * best for i in range(len(lines))]
    )


def _two_lines(line: str, measure: Measure) -> list[str] | None:
    """The line broken at the space that leaves its longer half shortest."""
    words = line.split(" ")
    splits = [
        [" ".join(words[:i]).rstrip(" "), " ".join(words[i:]).lstrip(" ")]
        for i in range(1, len(words))
    ]
    splits = [split for split in splits if all(split)]
    if not splits:
        return None
    return min(splits, key=lambda split: max(measure.width(part) for part in split))
