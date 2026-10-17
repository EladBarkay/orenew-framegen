"""Text in the SVG: built-in fonts, embedding, slots and direction (T-13a)."""

import hashlib
import re
from typing import Any

import pytest

from framegen.fonts import BUILT_IN, FILES
from framegen.render.svg import render_svg
from framegen.render.text import FontFile, Fonts, MissingFont, NoRoom, text_direction
from framegen.spec import read_spec

WORKSPACE_FONT = "font_" + "a" * 26
TTF = BUILT_IN["suez-one"].path.read_bytes()


def spec(inset: dict[str, float] | None = None, **parts: Any) -> Any:
    inset = inset or {"top": 0.1, "bottom": 0.2, "start": 0.1, "end": 0.1}
    return read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
        **parts,
    })  # fmt: skip


def headline(text: str = "נועה ועודד", font: str = "heebo-bold", **more: Any) -> dict[str, Any]:
    return {"text": text, "font": font, "color": "#3a2c12", "size": 0.05,
            "slot": "bottom-band", **more}  # fmt: skip


def stamp(slot: str, font: str = "amatic-sc-bold") -> dict[str, Any]:
    return {"source": "text", "text": "Orenew", "font": font, "color": "#000000",
            "size": 0.03, "slot": slot}  # fmt: skip


def texts(svg: str) -> list[dict[str, str]]:
    found: list[tuple[str, str]] = re.findall(r"<text ([^>]*)>([^<]*)</text>", svg)
    return [
        {**dict(re.findall(r'([\w-]+)="([^"]*)"', attributes)), "body": body}
        for attributes, body in found
    ]


def middle(text: dict[str, str], font: str) -> float:
    """The middle of a line's box (ascent above its baseline, descent below)."""
    line = Fonts({}).use(font).measure.line
    size = float(text["font-size"])
    return float(text["y"]) + (line.descent - line.ascent) * size / 2


def faces(svg: str) -> list[tuple[str, str]]:
    return re.findall(r'@font-face\{font-family:"([^"]+)";font-weight:([^;]+);', svg)


def test_the_built_in_files_are_the_pinned_ones() -> None:
    lines = (FILES / "SHA256SUMS").read_text().splitlines()
    sums = {file: digest for digest, file in (line.split("  ") for line in lines)}
    assert sums.keys() == {font.file for font in BUILT_IN.values()}
    for file, digest in sums.items():
        assert hashlib.sha256((FILES / file).read_bytes()).hexdigest() == digest, file


def test_each_built_in_font_has_its_licence_and_a_name_the_spec_takes() -> None:
    for name, font in BUILT_IN.items():
        spec(headline=headline(font=name))
        assert "SIL Open Font License" in (font.path.parent / "OFL.txt").read_text()


def test_nothing_is_embedded_without_text() -> None:
    assert "<style>" not in render_svg(spec(), "portrait", 600, 900)


def test_each_font_file_is_embedded_once() -> None:
    svg = render_svg(
        spec(headline=headline(font="heebo-bold"), stamp=stamp("top-band", font="heebo-light")),
        "portrait",
        600,
        900,
    )
    assert faces(svg) == [("fg-heebo", "1 1000")]
    assert [(t["font-family"], t["font-weight"]) for t in texts(svg)] == [
        ("fg-heebo", "700"),
        ("fg-heebo", "300"),
    ]


def test_a_static_family_has_a_face_per_weight() -> None:
    svg = render_svg(
        spec(headline=headline(font="david-libre"), stamp=stamp("top-band", "david-libre-bold")),
        "portrait",
        600,
        900,
    )
    assert faces(svg) == [("fg-davidlibre", "400"), ("fg-davidlibre", "700")]


def test_a_workspace_font_is_embedded_from_the_given_file() -> None:
    parts = {"headline": headline(font=WORKSPACE_FONT)}
    with pytest.raises(MissingFont):
        render_svg(spec(**parts), "portrait", 600, 900)
    svg = render_svg(spec(**parts), "portrait", 600, 900, fonts={WORKSPACE_FONT: FontFile(TTF)})
    assert faces(svg) == [(f"fg-{WORKSPACE_FONT}", "400")]
    assert "src:url(data:font/ttf;base64," in svg


@pytest.mark.parametrize(
    ("data", "fmt"),
    [(b"OTTO....", "opentype"), (b"true....", "truetype")],
)
def test_font_files_are_known_by_their_signature(data: bytes, fmt: str) -> None:
    assert FontFile(data).format == fmt


@pytest.mark.parametrize("data", [b"", b"<svg", b"wOFF....", b"wOF2...."])
def test_other_files_are_not_fonts(data: bytes) -> None:
    with pytest.raises(ValueError, match="TrueType or OpenType"):
        FontFile(data)


def test_text_is_escaped() -> None:
    svg = render_svg(spec(headline=headline("Noa <&> Oded")), "portrait", 600, 900)
    assert texts(svg)[0]["body"] == "Noa &lt;&amp;&gt; Oded"


@pytest.mark.parametrize(
    ("text", "direction"),
    [("נועה ועודד", "rtl"), ("Noa & Oded", "ltr"), ("Noa ועודד", "ltr"), ("12.10 נועה", "rtl"),
     ("2026", "rtl"), ("\u200fNoa", "rtl")],
)  # fmt: skip
def test_the_first_strong_character_sets_the_direction(text: str, direction: str) -> None:
    assert text_direction(text, "rtl") == direction


@pytest.mark.parametrize(
    ("text", "direction"),
    [("\u2068Noa\u2069 נועה", "rtl"), ("\u2068נועה\u2069 · 12.10", "ltr"),
     ("\u206612 10\u2069", "ltr")],
)  # fmt: skip
def test_isolates_do_not_set_the_direction(text: str, direction: str) -> None:
    # The last has no strong character outside its isolate: the default is used.
    assert text_direction(text, "ltr") == direction


def test_a_text_without_letters_takes_the_frame_direction() -> None:
    assert text_direction("12.10.26", "ltr") == "ltr"


def test_bands_hold_text_between_the_window_and_the_edge() -> None:
    svg = render_svg(spec(headline=headline(), stamp=stamp("top-band")), "portrait", 600, 900)
    bottom, top = texts(svg)
    # The window is 90 to 720 down; bands keep a margin of 2% of the shorter side (12).
    assert (bottom["x"], top["x"]) == ("300", "300")
    assert middle(bottom, "heebo-bold") == pytest.approx(810, abs=0.002)
    assert middle(top, "amatic-sc-bold") == pytest.approx(45, abs=0.002)
    assert bottom["font-size"] == "30"  # 5% of the shorter side: it fits
    assert "transform" not in bottom


@pytest.mark.parametrize(
    ("direction", "slot", "x"),
    [("rtl", "start-edge", "570"), ("rtl", "end-edge", "30"), ("ltr", "start-edge", "30"),
     ("ltr", "top-start", "75"), ("rtl", "top-start", "525")],
)  # fmt: skip
def test_start_and_end_follow_the_reading_direction(direction: str, slot: str, x: str) -> None:
    svg = render_svg(spec(stamp=stamp(slot)), "portrait", 600, 900, direction=direction)  # type: ignore[arg-type]
    (text,) = texts(svg)
    assert text["x"] == x


def test_edge_text_runs_up_the_frame() -> None:
    (text,) = texts(render_svg(spec(stamp=stamp("end-edge")), "portrait", 600, 900))
    # Turned about the middle of the left edge's area, level with the window's middle.
    assert text["transform"] == f"rotate(-90 {text['x']} 405)"
    assert middle(text, "amatic-sc-bold") == pytest.approx(405, abs=0.002)


def test_room_is_kept_under_the_headline() -> None:
    parts = {"headline": headline(), "stamp": stamp("under-headline")}
    above, under = texts(render_svg(spec(**parts), "portrait", 600, 900))
    # The bottom band's area is 732 to 888: the headline takes its first 60% (to 825.6),
    # less half the 12-pixel gap.
    assert middle(above, "heebo-bold") == pytest.approx(775.8, abs=0.002)
    assert middle(under, "amatic-sc-bold") == pytest.approx(859.8, abs=0.002)


def test_a_band_with_a_corner_taken_keeps_its_middle_half() -> None:
    parts = {"headline": headline(), "stamp": stamp("bottom-end")}
    band, corner = texts(render_svg(spec(**parts), "portrait", 600, 900))
    assert (band["x"], corner["x"]) == ("300", "75")
    alone = texts(render_svg(spec(headline=headline()), "portrait", 600, 900))
    assert alone[0]["x"] == "300"


def test_each_line_is_its_own_paragraph() -> None:
    lines = texts(render_svg(spec(headline=headline("נועה\nNoa")), "portrait", 600, 900))
    assert [(t["body"], t["direction"]) for t in lines] == [("נועה", "rtl"), ("Noa", "ltr")]
    # Stacked a line box apart, centred together.
    step = Fonts({}).use("heebo-bold").measure.line.height * 30
    assert float(lines[1]["y"]) - float(lines[0]["y"]) == pytest.approx(step, abs=0.002)
    assert (middle(lines[0], "heebo-bold") + middle(lines[1], "heebo-bold")) / 2 == (
        pytest.approx(810, abs=0.002)
    )


def test_an_unknown_built_in_font_is_a_missing_font() -> None:
    with pytest.raises(MissingFont, match="comic-sans"):
        Fonts({}).use("comic-sans")


def test_a_slot_with_no_room_is_an_error() -> None:
    no_top = {"top": 0, "bottom": 0.2, "start": 0.1, "end": 0.1}
    with pytest.raises(NoRoom, match="top-band"):
        render_svg(spec(no_top, stamp=stamp("top-band")), "portrait", 600, 900)


def test_text_is_kept_out_of_the_window() -> None:
    svg = render_svg(spec(headline=headline()), "portrait", 600, 900)
    assert re.search(r'<g mask="url\(#window-cut\)"><text ', svg)


def test_blank_lines_are_left_out() -> None:
    lines = texts(
        render_svg(spec(headline=headline("\nנועה\n \n\u200f\u200b\n")), "portrait", 600, 900)
    )
    assert [t["body"] for t in lines] == ["נועה"]
    assert middle(lines[0], "heebo-bold") == pytest.approx(810, abs=0.002)


def test_lines_never_run_past_their_area() -> None:
    many = "\n".join("abcdef")
    first, *_, last = texts(
        render_svg(spec(headline=headline(many, size=0.1)), "portrait", 600, 900)
    )
    # The bottom band's area is 732 to 888: six line boxes fill it exactly.
    line = Fonts({}).use("heebo-bold").measure.line
    size = float(last["font-size"])
    assert size < 60
    assert float(first["y"]) - line.ascent * size == pytest.approx(732, abs=0.01)
    assert float(last["y"]) + line.descent * size == pytest.approx(888, abs=0.01)


def test_no_room_under_the_headline_is_an_error() -> None:
    shallow = {"top": 0.1, "bottom": 0.04, "start": 0.1, "end": 0.1}
    parts = {"headline": headline(), "stamp": stamp("under-headline")}
    with pytest.raises(NoRoom, match="under the headline"):
        render_svg(spec(shallow, **parts), "portrait", 600, 900)


def test_characters_a_font_lacks_are_drawn_in_the_fallback() -> None:
    svg = render_svg(spec(headline=headline(font="great-vibes")), "portrait", 600, 900)
    assert texts(svg)[0]["font-family"] == "fg-greatvibes, fg-heebo"
    assert faces(svg) == [("fg-greatvibes", "400"), ("fg-heebo", "1 1000")]
    latin = render_svg(spec(headline=headline("Noa", font="great-vibes")), "portrait", 600, 900)
    assert texts(latin)[0]["font-family"] == "fg-greatvibes"
    assert faces(latin) == [("fg-greatvibes", "400")]
