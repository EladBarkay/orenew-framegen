import io
import struct
import time

import pytest
from PIL import Image

from framegen.assets.filetypes import HEADER_BYTES, TYPES, pixel_size


def encoded(image_format: str, size: tuple[int, int] = (300, 200), **options: object) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, image_format, **options)
    return out.getvalue()


def reader(data: bytes, reads: list[tuple[int, int]] | None = None):  # type: ignore[no-untyped-def]
    def read(offset: int, length: int) -> bytes:
        if reads is not None:
            reads.append((offset, length))
        return data[offset : offset + length]

    return read


def psd_header(width: int, height: int) -> bytes:
    return b"8BPS" + struct.pack(">H6sHIIHH", 1, b"\0" * 6, 3, height, width, 8, 3)


def heic(tiles: list[tuple[int, int]]) -> bytes:
    ftyp = struct.pack(">I", 24) + b"ftyp" + b"heic" + b"\0\0\0\0" + b"mif1heic"
    boxes = b"".join(
        struct.pack(">I", 20) + b"ispe" + b"\0\0\0\0" + struct.pack(">II", w, h) for w, h in tiles
    )
    return ftyp + boxes


SAMPLES = {
    "image/png": encoded("PNG"),
    "image/jpeg": encoded("JPEG"),
    "image/webp": encoded("WEBP"),
    "image/tiff": encoded("TIFF"),
    "image/vnd.adobe.photoshop": psd_header(300, 200) + b"\0" * 64,
    "image/heic": heic([(512, 512), (300, 200), (4032, 3024)]),
    "application/pdf": b"%PDF-1.7\n%...",
    "image/svg+xml": (
        b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"/>'
    ),
    "font/ttf": b"\0\1\0\0" + b"\0" * 60,
    "font/otf": b"OTTO" + b"\0" * 60,
    "font/woff2": b"wOF2" + b"\0" * 60,
}


@pytest.mark.parametrize("content_type", sorted(TYPES))
def test_each_type_is_recognised_only_as_itself(content_type: str) -> None:
    for other, data in SAMPLES.items():
        assert TYPES[content_type].matches(data) == (other == content_type), other


def test_a_page_is_not_any_type() -> None:
    page = b"<!doctype html><html><script>alert(1)</script></html>"
    assert not any(file_type.matches(page) for file_type in TYPES.values())


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/png", (300, 200)),
        ("image/jpeg", (300, 200)),
        ("image/webp", (300, 200)),
        ("image/tiff", (300, 200)),
        ("image/vnd.adobe.photoshop", (300, 200)),
        ("image/heic", (4032, 3024)),
        ("image/svg+xml", (300, 200)),
        ("application/pdf", None),
        ("font/otf", None),
    ],
)
def test_pixel_size(content_type: str, expected: tuple[int, int] | None) -> None:
    assert pixel_size(content_type, reader(SAMPLES[content_type])) == expected


def test_svg_size_from_the_view_box() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10cm" viewBox="0 0 1200 800">'
    assert pixel_size("image/svg+xml", reader(svg)) == (1200, 800)


def test_svg_with_a_comment_before_the_root() -> None:
    svg = b"\xef\xbb\xbf<!-- made by hand -->\n<svg width='5' height='7'></svg>"
    assert TYPES["image/svg+xml"].matches(svg)
    assert pixel_size("image/svg+xml", reader(svg)) == (5, 7)


def test_a_size_far_into_the_file_is_read_in_parts() -> None:
    # A JPEG with a large comment before its size: the size is past the first block.
    jpeg = encoded("JPEG", (640, 480))
    padded = jpeg[:2] + (b"\xff\xfe" + struct.pack(">H", 65535) + b"x" * 65533) * 2 + jpeg[2:]
    reads: list[tuple[int, int]] = []
    assert pixel_size("image/jpeg", reader(padded, reads)) == (640, 480)
    assert len(reads) > 1
    assert all(length <= HEADER_BYTES for _, length in reads)


def test_a_damaged_header_has_no_size() -> None:
    assert pixel_size("image/png", reader(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)) is None


def test_svg_recognition_takes_linear_time() -> None:
    started = time.monotonic()
    assert TYPES["image/svg+xml"].matches(b"<!---->" * 10_000 + b"<svg>")
    assert not TYPES["image/svg+xml"].matches(b"<!---->" * 10_000 + b"x")
    assert not TYPES["image/svg+xml"].matches(b"<!--" * 10_000)
    assert time.monotonic() - started < 1


def test_avif_is_not_heic() -> None:
    avif = struct.pack(">I", 24) + b"ftyp" + b"avif" + b"\0\0\0\0" + b"mif1miaf"
    assert not TYPES["image/heic"].matches(avif)


@pytest.mark.parametrize(
    ("content_type", "data"),
    [
        ("image/vnd.adobe.photoshop", psd_header(0xFFFFFFFF, 10)),
        ("image/heic", heic([(0xFFFFFFFF, 0xFFFFFFFF)])),
        ("image/svg+xml", b'<svg width="99999999999" height="10">'),
        ("image/svg+xml", b'<svg viewBox="0 0 1e999 1">'),
        ("image/svg+xml", b'<svg viewBox="0 0 inf nan">'),
        ("image/svg+xml", b'<svg width="0" height="10">'),
    ],
)
def test_impossible_sizes_are_no_size(content_type: str, data: bytes) -> None:
    assert pixel_size(content_type, reader(data)) is None


def test_long_svg_dimensions_take_linear_time() -> None:
    started = time.monotonic()
    svg = b'<svg width="' + b"1" * 60_000 + b'x" height="1">'
    assert pixel_size("image/svg+xml", reader(svg)) is None
    assert time.monotonic() - started < 1


def test_svg_with_an_internal_doctype_subset() -> None:
    # As Adobe Illustrator writes them.
    svg = (
        b'<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd" [\n'
        b'  <!ENTITY ns_extend "http://ns.adobe.com/Extensibility/1.0/">\n]>\n'
        b'<svg version="1.1" width="640px" height="480px">'
    )
    assert TYPES["image/svg+xml"].matches(svg)
    assert pixel_size("image/svg+xml", reader(svg)) == (640, 480)


def test_svg_size_comes_from_the_root_not_a_comment() -> None:
    svg = b'<!-- <svg width="10" height="10"> --><svg width="800" height="600">'
    assert pixel_size("image/svg+xml", reader(svg)) == (800, 600)


@pytest.mark.parametrize(
    ("mode", "options"),
    [("RGB", {}), ("RGB", {"lossless": True}), ("RGBA", {}), ("RGBA", {"exif": b"Exif\0\0"})],
)
def test_webp_size_from_its_header_alone(mode: str, options: dict[str, object]) -> None:
    out = io.BytesIO()
    Image.effect_noise((1500, 1100), 64).convert(mode).save(out, "WEBP", **options)
    data = out.getvalue()
    reads: list[tuple[int, int]] = []
    assert pixel_size("image/webp", reader(data, reads)) == (1500, 1100)
    assert len(reads) == 1
