"""Image and brand-kit stamps (T-15a)."""

import re

import pytest

from framegen.render.svg import MissingBrandStamp, MissingImage, render_svg
from framegen.render.text import NoRoom
from framegen.spec.text import BrandText
from tests.stamps import LOGO, png, spec


def image_attributes(svg: str) -> dict[str, str]:
    # The last <image>: the stamp (no layer here draws one).
    found = re.findall(r"<image ([^>]*)/>", svg)
    return dict(re.findall(r'([\w-]+)="([^"]*)"', found[-1]))


def test_an_image_stamp_is_its_size_and_runs_up_an_edge() -> None:
    stamp = {"source": "image", "image": LOGO, "slot": "end-edge", "size": 0.08}
    svg = render_svg(spec(stamp), "portrait", 600, 900, images={LOGO: png(200, 100)})
    image = image_attributes(svg)
    # Longest side 8% of 600: 48 x 24, centred in the left edge (rtl end) at (30, 405).
    assert (image["width"], image["height"]) == ("48", "24")
    assert (image["x"], image["y"]) == ("6", "393")
    assert image["transform"] == "rotate(-90 30 405)"
    assert re.search(r'<g mask="url\(#window-cut\)"><image ', svg)


def test_an_image_stamp_shrinks_to_fit_its_slot() -> None:
    stamp = {"source": "image", "image": LOGO, "slot": "bottom-band", "size": 0.5}
    svg = render_svg(spec(stamp), "portrait", 600, 900, images={LOGO: png(200, 100)})
    image = image_attributes(svg)
    # 300 x 150 asked; the band's area is 576 x 156, so it fits as asked.
    assert (image["width"], image["height"], image["y"]) == ("300", "150", "735")
    tall = render_svg(spec(stamp), "portrait", 600, 900, images={LOGO: png(100, 200)})
    image = image_attributes(tall)
    # 150 x 300 asked: only 156 deep, so 78 x 156.
    assert (image["width"], image["height"]) == ("78", "156")
    assert "transform" not in image


def test_an_image_stamp_keeps_its_opacity() -> None:
    stamp = {"source": "image", "image": LOGO, "slot": "top-end", "opacity": 0.5}
    image = image_attributes(render_svg(spec(stamp), "portrait", 600, 900,
                                        images={LOGO: png(10, 10)}))  # fmt: skip
    assert image["opacity"] == "0.5"


def test_an_image_stamp_needs_its_image() -> None:
    with pytest.raises(MissingImage):
        render_svg(spec({"source": "image", "image": LOGO, "slot": "top-end"}), "portrait",
                   600, 900)  # fmt: skip


def test_the_brand_kits_text_stamp_is_drawn_in_its_font() -> None:
    stamp = {"source": "brand-kit", "slot": "end-edge", "size": 0.03}
    brand = BrandText(text="Orenew צילום\n050-1234567", font="amatic-sc-bold", color="#3a2c12")
    svg = render_svg(spec(stamp), "portrait", 600, 900, brand_stamp=brand)
    texts = re.findall(r"<text ([^>]*)>([^<]*)</text>", svg)
    assert [body for _, body in texts] == ["Orenew צילום", "050-1234567"]
    assert 'font-family="fg-amaticsc"' in texts[0][0]
    assert 'fill="#3a2c12"' in texts[0][0]
    assert "rotate(-90" in texts[0][0]


def test_the_brand_kits_image_stamp_is_drawn_like_an_image_stamp() -> None:
    stamp = {"source": "brand-kit", "slot": "bottom-start", "size": 0.1}
    svg = render_svg(spec(stamp), "portrait", 600, 900, brand_stamp=png(60, 30))
    image = image_attributes(svg)
    assert (image["width"], image["height"]) == ("60", "30")


def test_a_spec_using_the_brand_kit_needs_its_stamp() -> None:
    with pytest.raises(MissingBrandStamp):
        render_svg(spec({"source": "brand-kit", "slot": "top-end"}), "portrait", 600, 900)


def test_a_stamp_too_thin_for_its_slot_is_an_error() -> None:
    stamp = {"source": "image", "image": LOGO, "slot": "top-end", "size": 0.5}
    with pytest.raises(NoRoom):
        render_svg(spec(stamp), "portrait", 600, 900, images={LOGO: png(4000, 2)})


def test_a_brand_kit_text_stamp_is_no_taller_than_any_text() -> None:
    stamp = {"source": "brand-kit", "slot": "bottom-band", "size": 0.5}
    brand = BrandText(text="ש", font="heebo", color="#000000")
    svg = render_svg(spec(stamp), "portrait", 600, 900, brand_stamp=brand)
    sizes = [float(size) for size in re.findall(r'font-size="([\d.]+)"', svg)]
    assert sizes and max(sizes) <= 0.25 * 600
