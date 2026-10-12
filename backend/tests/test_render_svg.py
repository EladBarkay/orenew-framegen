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


def layers(root: ET.Element, *, cut: bool = True) -> list[ET.Element]:
    """The drawn layers in order; cut ones are each wrapped in a group with the mask."""
    drawn = []
    for element in root:
        if element.tag.endswith("defs"):
            continue
        if element.tag.endswith("}g"):
            assert element.attrib["mask"] == "url(#window-cut)" and len(element) == 1
            drawn.append(element[0])
        else:
            assert not cut, "a layer was drawn without the window cut"
            drawn.append(element)
    return drawn


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
    assert image.attrib["preserveAspectRatio"] == "xMidYMid meet"
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
    assert rtl.attrib["transform"] == "rotate(30 750 375)"  # clockwise in both directions
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


def test_layers_keep_their_order_and_only_overlapping_ones_skip_the_cut() -> None:
    root = draw(spec([band("top"), piece(overlapsWindow=True), band("bottom")]))
    top, flower, bottom = layers(root, cut=False)
    assert [element.tag.split("}")[1] for element in (top, flower, bottom)] == [
        "rect", "image", "rect"]  # fmt: skip
    # The flower is not in a cut group; the bottom band, listed after it, covers it.
    assert [element.tag.split("}")[1] for element in root][1:] == ["g", "image", "g"]


def test_a_rotated_layer_keeps_the_cut_in_place() -> None:
    shape = {"kind": "vector", "shape": "rectangle", "rotate": 45, "color": "#000000",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}  # fmt: skip
    root = draw(spec([shape]))
    group = list(root)[1]
    assert "transform" not in group.attrib and "transform" in group[0].attrib


@pytest.mark.parametrize(("orientation", "size"), [("portrait", (1500, 1000)),
                                                   ("landscape", (1000, 1500))])  # fmt: skip
def test_the_size_must_fit_the_orientation(orientation: str, size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="is not the"):
        render_svg(spec([band("top")]), orientation, *size)  # type: ignore[arg-type]


@pytest.mark.parametrize("size", [(1000, 1000), (1000, 3000), (1000, 1502)])
def test_the_size_must_have_the_spec_aspect(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="aspect 2:3"):
        render_svg(spec([band("top")]), "portrait", *size)


def test_a_size_one_pixel_off_the_aspect_is_fine() -> None:
    assert render_svg(spec([band("top")]), "portrait", 1001, 1500)


def test_the_orientation_is_checked() -> None:
    with pytest.raises(ValueError, match="orientation"):
        render_svg(spec([band("top")]), "Portrait", 1000, 1500)  # type: ignore[arg-type]


def test_a_size_too_small_for_the_window_is_an_error() -> None:
    narrow = {"top": 0, "bottom": 0, "start": 0.4, "end": 0.4}
    frame = spec([band("top")])
    frame = frame.model_copy(update={"window": frame.window.model_copy(update={
        "portrait": frame.window.portrait.model_copy(update={
            "inset": frame.window.portrait.inset.model_copy(update=narrow)})})})  # fmt: skip
    with pytest.raises(ValueError, match="too small"):
        render_svg(frame, "portrait", 2, 3)


def test_the_window_cut_has_no_partial_pixels() -> None:
    oval = draw(spec([band("top")], shape="oval")).find("s:defs/s:mask/s:ellipse", NS)
    assert oval is not None and oval.attrib["shape-rendering"] == "crispEdges"
    masked = render_svg(spec([band("top")], shape="mask", mask=MASK), "portrait", 1000, 1500,
                        images=IMAGES)  # fmt: skip
    assert '<feFuncA type="discrete" tableValues="0 1"/>' in masked


def test_a_band_meets_the_window_on_a_whole_pixel() -> None:
    inset = {"top": 0.1, "bottom": 0, "start": 0, "end": 0}
    frame = read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "bar", "layers": [band("top", 0.1)]},
    })  # fmt: skip
    root = ET.fromstring(render_svg(frame, "portrait", 1010, 1515))
    window = root.find("s:defs/s:mask", NS)
    assert window is not None
    (top,) = layers(root)
    # 151.5 px both: the band ends where the window starts, at 152.
    assert numbers(top, "height") == numbers(window[1], "y") == (152,)


def test_an_image_has_a_size() -> None:
    with pytest.raises(ValueError, match="at least"):
        Image("data:image/png;base64,", width=0, height=10)


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/flower.png",
        "file:///etc/passwd",
        "data:text/html;base64,PGI+",
        "data:image/png,raw",
        "data:image/png;base64,AAAA\n",
        "data:image/png;base64,AA AA",
    ],
)
def test_images_are_only_data_urls(href: str) -> None:
    with pytest.raises(ValueError, match="data: URL"):
        Image(href, width=10, height=10)


def test_the_direction_is_checked() -> None:
    with pytest.raises(ValueError, match="direction"):
        render_svg(spec([band("top")]), "portrait", 100, 150, direction="RTL")  # type: ignore[arg-type]


def test_the_window_has_whole_pixel_edges() -> None:
    frame = read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle",
                   "portrait": {"inset": {"top": 0.0625, "bottom": 0.0625,
                                          "start": 0.0333, "end": 0}},
                   "landscape": {"inset": {"top": 0, "bottom": 0, "start": 0, "end": 0}}},
        "decoration": {"archetype": "surround", "layers": [band("top")]},
    })  # fmt: skip
    cut = ET.fromstring(render_svg(frame, "portrait", 1000, 1500)).find("s:defs/s:mask", NS)
    assert cut is not None
    # 93.75 and 1406.25 px from the top, 33.3 px from the right: whole pixels.
    assert numbers(cut[1], "x", "y", "width", "height") == (0, 94, 967, 1312)


def test_a_caption_bar_may_cover_the_photo() -> None:
    # attachments/23.9.26: the window is the whole frame and the bar lies over the photo.
    bar = {"kind": "vector", "shape": "bar", "edge": "bottom", "distance": 0.09,
           "thickness": 0.074, "color": "#ffffff", "overlapsWindow": True}  # fmt: skip
    root = draw(spec([band("top"), bar]))
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
