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
TTF = b"\x00\x01\x00\x00" + b"rest of the font"


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
    [(b"OTTO....", "opentype"), (b"wOF2....", "woff2"), (b"true....", "truetype")],
)
def test_font_files_are_known_by_their_signature(data: bytes, fmt: str) -> None:
    assert FontFile(data).format == fmt


@pytest.mark.parametrize("data", [b"", b"<svg", b"wOFF...."])
def test_other_files_are_not_fonts(data: bytes) -> None:
    with pytest.raises(ValueError, match="TrueType, OpenType or WOFF2"):
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


def test_a_text_without_letters_takes_the_frame_direction() -> None:
    assert text_direction("12.10.26", "ltr") == "ltr"


def test_bands_hold_text_between_the_window_and_the_edge() -> None:
    svg = render_svg(spec(headline=headline(), stamp=stamp("top-band")), "portrait", 600, 900)
    bottom, top = texts(svg)
    # The window is 90 to 720 down; bands keep a margin of 2% of the shorter side (12).
    assert (bottom["x"], bottom["y"]) == ("300", "810")
    assert (top["x"], top["y"]) == ("300", "45")
    assert bottom["font-size"] == "30"  # 5% of the shorter side
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
    assert text["transform"] == f"rotate(-90 {text['x']} {text['y']})"
    assert text["y"] == "405"  # the middle of the window's height


def test_room_is_kept_under_the_headline() -> None:
    parts = {"headline": headline(), "stamp": stamp("under-headline")}
    above, under = texts(render_svg(spec(**parts), "portrait", 600, 900))
    # The bottom band's area is 732 to 888: the headline takes its first 60% (to 825.6),
    # less half the 12-pixel gap.
    assert (above["y"], under["y"]) == ("775.8", "859.8")


def test_a_band_with_a_corner_taken_keeps_its_middle_half() -> None:
    parts = {"headline": headline(), "stamp": stamp("bottom-end")}
    band, corner = texts(render_svg(spec(**parts), "portrait", 600, 900))
    assert (band["x"], corner["x"]) == ("300", "75")
    alone = texts(render_svg(spec(headline=headline()), "portrait", 600, 900))
    assert alone[0]["x"] == "300"


def test_each_line_is_its_own_paragraph() -> None:
    lines = texts(render_svg(spec(headline=headline("נועה\nNoa")), "portrait", 600, 900))
    assert [(t["body"], t["y"], t["direction"]) for t in lines] == [
        ("נועה", "792", "rtl"),
        ("Noa", "828", "ltr"),
    ]


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
    lines = texts(render_svg(spec(headline=headline("\nנועה\n \n")), "portrait", 600, 900))
    assert [(t["body"], t["y"]) for t in lines] == [("נועה", "810")]


def test_lines_never_run_past_their_area() -> None:
    many = "\n".join("abcdef")
    (*_, last) = texts(render_svg(spec(headline=headline(many, size=0.1)), "portrait", 600, 900))
    # The bottom band's area is 732 to 888 (156 deep): six lines of 1.2 x 21.667.
    assert last["font-size"] == "21.667"
    assert float(last["y"]) + float(last["font-size"]) * 0.6 == pytest.approx(888)


def test_no_room_under_the_headline_is_an_error() -> None:
    shallow = {"top": 0.1, "bottom": 0.04, "start": 0.1, "end": 0.1}
    parts = {"headline": headline(), "stamp": stamp("under-headline")}
    with pytest.raises(NoRoom, match="under the headline"):
        render_svg(spec(shallow, **parts), "portrait", 600, 900)
