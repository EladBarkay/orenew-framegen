"""Measuring text with HarfBuzz and fitting it to its area (T-13b)."""

import io

import pytest
from fontTools.ttLib import TTFont

from framegen.fonts import BUILT_IN
from framegen.render.measure import WRAP_BELOW, Measure, fit
from framegen.render.text import FontFile, Fonts

HEEBO = Fonts({}).use("heebo-bold").measure


def test_width_grows_with_the_text_and_weight() -> None:
    assert HEEBO.width("נועה ועודד") > HEEBO.width("נועה") > 0
    assert Fonts({}).use("heebo-black").measure.width("נועה") > Fonts({}).use(
        "heebo-light"
    ).measure.width("נועה")


def test_the_line_box_is_the_fonts_own() -> None:
    # Heebo's ascender and descender are 2146 and -862 on a 2048 grid.
    assert HEEBO.line.ascent == pytest.approx(2146 / 2048)
    assert HEEBO.line.descent == pytest.approx(862 / 2048)


def test_a_woff2_file_measures_as_its_truetype_original() -> None:
    path = BUILT_IN["suez-one"].path
    font = TTFont(path)
    font.flavor = "woff2"
    out = io.BytesIO()
    font.save(out)
    woff2 = out.getvalue()
    assert woff2[:4] == b"wOF2"
    original = Measure(path.read_bytes(), None)
    workspace = Fonts({"font_" + "b" * 26: FontFile(woff2)}).use("font_" + "b" * 26).measure
    assert workspace.width("נועה ועודד") == original.width("נועה ועודד")
    assert workspace.line == original.line


def test_short_text_keeps_its_size() -> None:
    layout = fit(["נועה"], HEEBO, length=500, depth=100, size=30)
    assert (layout.lines, layout.size) == (["נועה"], 30)


def test_a_long_line_shrinks_to_the_length() -> None:
    text = "נועה ועודד"
    layout = fit([text], HEEBO, length=120, depth=100, size=30)
    assert layout.lines == [text]
    assert layout.size * HEEBO.width(text) == pytest.approx(120)
    assert layout.size >= WRAP_BELOW * 30


def test_a_line_that_would_shrink_too_far_is_broken_in_two() -> None:
    text = "החתונה של נועה ועודד"
    one = 300 / HEEBO.width(text)  # the size it would have on one line
    layout = fit([text], HEEBO, length=300, depth=200, size=60)
    assert one < WRAP_BELOW * 60
    assert layout.lines == ["החתונה של", "נועה ועודד"]  # the most even break
    assert layout.size > one


def test_two_lines_are_kept_only_if_they_are_bigger() -> None:
    text = "החתונה של נועה ועודד"
    # Too shallow for two lines: one line, shrunk, is bigger.
    layout = fit([text], HEEBO, length=300, depth=40, size=60)
    assert layout.lines == [text]


def test_a_single_word_is_never_broken() -> None:
    layout = fit(["אבגדהוזחטיכלמנסעפצקרשת"], HEEBO, length=100, depth=200, size=60)
    assert len(layout.lines) == 1


def test_given_lines_are_kept_and_fit_the_depth() -> None:
    layout = fit(["נועה", "ועודד", "2026"], HEEBO, length=500, depth=60, size=30)
    assert layout.lines == ["נועה", "ועודד", "2026"]
    assert layout.size * 3 * HEEBO.line.height == pytest.approx(60)


def test_the_lines_are_centred_on_the_middle() -> None:
    layout = fit(["נועה", "ועודד"], HEEBO, length=500, depth=200, size=30)
    top = layout.baselines[0] - HEEBO.line.ascent * 30
    bottom = layout.baselines[1] + HEEBO.line.descent * 30
    assert top == pytest.approx(-bottom)
    assert layout.baselines[1] - layout.baselines[0] == pytest.approx(HEEBO.line.height * 30)
