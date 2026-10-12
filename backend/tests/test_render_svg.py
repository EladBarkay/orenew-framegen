import xml.etree.ElementTree as ET
from typing import Any

import pytest

from framegen.render.svg import Image, MissingImage, render_svg
from framegen.spec import FrameSpec, read_spec

NS = {"s": "http://www.w3.org/2000/svg"}
PIECE = "pc_" + "a2" * 13
MASK = "ast_" + "b3" * 13
IMAGES = {
    PIECE: Image("data:image/png;base64,AAAA", width=200, height=100),
    MASK: Image("data:image/png;base64,BBBB", width=10, height=10),
}


def spec(layers: list[dict[str, Any]], **window: Any) -> FrameSpec:
    inset = {"top": 0.1, "bottom": 0.2, "start": 0.05, "end": 0.15}
    return read_spec(
        {
            "specVersion": 1,
            "aspect": {"portrait": "2:3", "landscape": "3:2"},
            "window": {"shape": "rectangle", "portrait": {"inset": inset},
                       "landscape": {"inset": inset}, **window},
            "decoration": {"archetype": "surround", "layers": layers},
        }
    )  # fmt: skip


def draw(
    frame: FrameSpec, direction: str = "rtl", size: tuple[int, int] = (1000, 1500)
) -> ET.Element:
    text = render_svg(frame, "portrait", *size, direction=direction, images=IMAGES)  # type: ignore[arg-type]
    return ET.fromstring(text)


def numbers(element: ET.Element, *names: str) -> tuple[float, ...]:
    return tuple(float(element.attrib[name]) for name in names)


def band(edge: str, thickness: float = 0.1) -> dict[str, Any]:
    return {"kind": "vector", "shape": "band", "edge": edge, "thickness": thickness,
            "color": "#ffffff"}  # fmt: skip


def piece(**changes: Any) -> dict[str, Any]:
    return {"kind": "piece", "piece": PIECE, "anchor": "bottom-start", "size": 0.2, **changes}


def layers(root: ET.Element) -> list[ET.Element]:
    group = root.find("s:g", NS)
    assert group is not None and group.attrib["mask"] == "url(#window-cut)"
    return list(group)


def test_the_document_has_the_requested_size() -> None:
    root = draw(spec([band("bottom")]), size=(1200, 1800))
    assert (root.attrib["width"], root.attrib["height"]) == ("1200", "1800")
    assert root.attrib["viewBox"] == "0 0 1200 1800"


@pytest.mark.parametrize(("direction", "x"), [("rtl", 150), ("ltr", 50)])
def test_start_follows_the_reading_direction(direction: str, x: float) -> None:
    # start 0.05 and end 0.15 of 1000 px: in Hebrew the start is the right side.
    cut = draw(spec([band("bottom")]), direction).find("s:defs/s:mask", NS)
    assert cut is not None
    full, window = list(cut)
    assert numbers(full, "x", "y", "width", "height") == (0, 0, 1000, 1500)
    assert full.attrib["fill"] == "#ffffff" and window.attrib["fill"] == "#000000"
    assert numbers(window, "x", "y", "width", "height") == (x, 150, 800, 1050)


def test_window_shapes() -> None:
    rounded = draw(spec([band("top")], shape="rounded", radius=0.1)).find(
        "s:defs/s:mask/s:rect[2]", NS
    )
    assert rounded is not None and rounded.attrib["rx"] == "80"  # 0.1 of the 800 px side
    oval = draw(spec([band("top")], shape="oval")).find("s:defs/s:mask/s:ellipse", NS)
    assert oval is not None
    assert numbers(oval, "cx", "cy", "rx", "ry") == (550, 675, 400, 525)
    arch = draw(spec([band("top")], shape="arch")).find("s:defs/s:mask/s:path", NS)
    assert arch is not None
    assert arch.attrib["d"] == "M 150 1200 L 150 550 A 400 400 0 0 1 950 550 L 950 1200 Z"


def test_a_mask_window_uses_its_image() -> None:
    root = draw(spec([band("top")], shape="mask", mask=MASK))
    image = root.find("s:defs/s:mask/s:image", NS)
    assert image is not None and image.attrib["href"] == IMAGES[MASK].href
    assert image.attrib["filter"] == "url(#alpha-to-black)"
    assert numbers(image, "x", "y", "width", "height") == (150, 150, 800, 1050)
    with pytest.raises(MissingImage):
        render_svg(spec([band("top")], shape="mask", mask=MASK), "portrait", 100, 150)


@pytest.mark.parametrize(
    ("layer", "box"),
    [
        (band("top"), (0, 0, 1000, 150)),
        (band("bottom", 0.2), (0, 1200, 1000, 300)),
        (band("start"), (900, 0, 100, 1500)),  # right, in Hebrew
        (band("end"), (0, 0, 100, 1500)),
        ({"kind": "vector", "shape": "bar", "edge": "bottom", "distance": 0.1,
          "thickness": 0.05, "color": "#000000"}, (0, 1275, 1000, 75)),
    ],
)  # fmt: skip
def test_bands_and_bars(layer: dict[str, Any], box: tuple[float, ...]) -> None:
    (rect,) = layers(draw(spec([layer])))
    assert numbers(rect, "x", "y", "width", "height") == box


def test_strokes() -> None:
    frame_line = {
        "kind": "vector",
        "shape": "stroke",
        "around": "frame",
        "width": 0.01,
        "offset": 0.02,
        "color": "#c9a24a",
        "opacity": 0.5,
    }
    (rect,) = layers(draw(spec([frame_line])))
    # 10 px wide, its centre 25 px in from the edge.
    assert numbers(rect, "x", "y", "width", "height", "stroke-width") == (25, 25, 950, 1450, 10)
    assert (rect.attrib["fill"], rect.attrib["stroke"], rect.attrib["opacity"]) == (
        "none",
        "#c9a24a",
        "0.5",
    )

    window_line = {**frame_line, "around": "window"}
    (around,) = layers(draw(spec([window_line], shape="rounded", radius=0.1)))
    assert numbers(around, "x", "y", "width", "height", "rx") == (125, 125, 850, 1100, 105)


def test_shapes_rotate_about_their_centre_and_follow_the_direction() -> None:
    shape = {
        "kind": "vector",
        "shape": "rectangle",
        "rotate": 30,
        "color": "#ff000080",
        "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
    }
    (rtl,) = layers(draw(spec([shape])))
    assert numbers(rtl, "x", "y", "width", "height") == (600, 300, 300, 150)
    assert rtl.attrib["transform"] == "rotate(30 750 375)"
    (ltr,) = layers(draw(spec([{**shape, "shape": "ellipse", "rotate": 0}]), "ltr"))
    assert numbers(ltr, "cx", "cy", "rx", "ry") == (250, 375, 150, 75)
    assert "transform" not in ltr.attrib


def test_pieces_sit_on_their_anchor() -> None:
    # 0.2 of the 1000 px shorter side: the 200x100 image becomes 200x100 px.
    (rtl,) = layers(draw(spec([piece()])))
    assert numbers(rtl, "x", "y", "width", "height") == (800, 1400, 200, 100)
    (ltr,) = layers(draw(spec([piece()]), "ltr"))
    assert numbers(ltr, "x", "y") == (0, 1400)
    (moved,) = layers(draw(spec([piece(anchor="center", offset={"x": 0.1, "y": -0.1})])))
    assert numbers(moved, "x", "y") == (300, 550)


def test_pieces_turn_and_mirror_in_place() -> None:
    (turned,) = layers(draw(spec([piece(rotate=-90, mirror="inline")])))
    assert turned.attrib["transform"] == (
        "rotate(-90 900 1450) translate(900 1450) scale(-1 1) translate(-900 -1450)"
    )


def test_overlapping_pieces_are_drawn_after_the_cut() -> None:
    root = draw(spec([band("top"), piece(overlapsWindow=True), band("bottom")]))
    assert [element.tag.split("}")[1] for element in layers(root)] == ["rect", "rect"]
    over = root.find("s:image", NS)
    assert over is not None and numbers(over, "x", "y") == (800, 1400)
    assert list(root)[-1] is over


def test_a_caption_bar_may_cover_the_photo() -> None:
    # attachments/23.9.26: the window is the whole frame and the bar lies over the photo.
    bar = {"kind": "vector", "shape": "bar", "edge": "bottom", "distance": 0.09,
           "thickness": 0.074, "color": "#ffffff", "overlapsWindow": True}  # fmt: skip
    root = draw(spec([band("top"), bar]))
    assert len(layers(root)) == 1
    over = list(root)[-1]
    assert over.tag.endswith("rect") and numbers(over, "y") == (1254,)


def test_the_same_input_gives_the_same_text() -> None:
    frame = spec([band("top"), piece(rotate=12.345678)], shape="rounded", radius=0.123456)
    first = render_svg(frame, "portrait", 1333, 2000, images=IMAGES)
    assert first == render_svg(frame, "portrait", 1333, 2000, images=IMAGES)
    assert "rotate(12.346 " in first


def test_a_missing_piece_image_is_an_error() -> None:
    with pytest.raises(MissingImage, match=PIECE):
        render_svg(spec([piece()]), "portrait", 100, 150)


def test_a_size_below_one_pixel_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least"):
        render_svg(spec([band("top")]), "portrait", 0, 150)
