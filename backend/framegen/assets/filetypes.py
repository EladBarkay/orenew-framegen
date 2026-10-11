"""The file types FrameGen accepts (DESIGN.md section 6.2), recognised by their content.

A declared type is only believed once the file's first bytes agree with it, so a page or
script can never be stored as, and later served as, an image. Pixel size is read from the
file's header without decoding the image.
"""

import io
import math
import re
import struct
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PIL import Image, UnidentifiedImageError

HEADER_BYTES = 64 * 1024
"""How much of a file is read to recognise it and find its pixel size."""

MiB = 1024 * 1024

Family = Literal["image", "document", "font"]


@dataclass(frozen=True)
class FileType:
    content_type: str
    extensions: tuple[str, ...]
    max_size: int
    family: Family
    matches: Callable[[bytes], bool]


def _starts(*prefixes: bytes) -> Callable[[bytes], bool]:
    return lambda head: head.startswith(prefixes)


def _is_webp(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


# HEVC brands only: the generic mif1/msf1 are also listed by AVIF files.
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx"}


def _is_heif(head: bytes) -> bool:
    if head[4:8] != b"ftyp":
        return False
    (box_size,) = struct.unpack(">I", head[:4])
    brands = [head[8:12]] + [head[i : i + 4] for i in range(16, min(box_size, 64), 4)]
    return any(brand in _HEIF_BRANDS for brand in brands)


_SVG_PROLOG = ((b"<?xml", b"?>"), (b"<!--", b"-->"), (b"<!DOCTYPE", b">"))


def _is_svg(head: bytes) -> bool:
    """The root element is <svg>, after an optional XML declaration, comments and doctype.

    A plain scan, each step moving forward, so any input is checked in linear time.
    """
    position = len(head) - len(head.removeprefix(b"\xef\xbb\xbf"))
    while True:
        while position < len(head) and head[position : position + 1].isspace():
            position += 1
        for opening, closing in _SVG_PROLOG:
            if head.startswith(opening, position):
                end = head.find(closing, position + len(opening))
                if end < 0:
                    return False
                position = end + len(closing)
                break
        else:
            after = head[position + 4 : position + 5]
            return head.startswith(b"<svg", position) and (after.isspace() or after in (b">", b"/"))


TYPES: dict[str, FileType] = {
    t.content_type: t
    for t in [
        FileType("image/png", (".png",), 200 * MiB, "image", _starts(b"\x89PNG\r\n\x1a\n")),
        FileType("image/jpeg", (".jpg", ".jpeg"), 200 * MiB, "image", _starts(b"\xff\xd8\xff")),
        FileType("image/webp", (".webp",), 200 * MiB, "image", _is_webp),
        FileType("image/heic", (".heic", ".heif"), 200 * MiB, "image", _is_heif),
        FileType("image/tiff", (".tif", ".tiff"), 1024 * MiB, "image", _starts(b"II*\0", b"MM\0*")),
        FileType(
            "image/vnd.adobe.photoshop", (".psd", ".psb"), 2048 * MiB, "image", _starts(b"8BPS")
        ),
        FileType("application/pdf", (".pdf",), 200 * MiB, "document", _starts(b"%PDF-")),
        FileType("image/svg+xml", (".svg",), 5 * MiB, "image", _is_svg),
        FileType("font/ttf", (".ttf",), 50 * MiB, "font", _starts(b"\0\1\0\0", b"true")),
        FileType("font/otf", (".otf",), 50 * MiB, "font", _starts(b"OTTO")),
        FileType("font/woff2", (".woff2",), 50 * MiB, "font", _starts(b"wOF2")),
    ]
}


def pixel_size(content_type: str, read: Callable[[int, int], bytes]) -> tuple[int, int] | None:
    """Width and height in pixels, or None when the type has none (PDF, fonts) or the
    header does not say. ``read(offset, length)`` reads part of the file, so formats that
    keep their size away from the start (some TIFFs) still work without a full download.
    """
    head = read(0, HEADER_BYTES)
    if content_type == "image/vnd.adobe.photoshop":
        if len(head) < 26:
            return None
        height, width = struct.unpack(">II", head[14:22])
        return _plausible((width, height))
    if content_type == "image/heic":
        return _plausible(_heif_size(head))
    if content_type == "image/svg+xml":
        return _plausible(_svg_size(head))
    if TYPES[content_type].family != "image":
        return None
    with warnings.catch_warnings():
        # Only the header is read, so a very large image is no decompression risk here.
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BufferedReader(_RangedFile(read, head))) as image:
                return _plausible(image.size)
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
            return None


def _heif_size(head: bytes) -> tuple[int, int] | None:
    """The largest 'ispe' (image spatial extents) box: the full image, not a tile or the
    thumbnail."""
    sizes = []
    for match in re.finditer(rb"ispe", head):
        start = match.end() + 4  # version and flags
        if start + 8 <= len(head):
            sizes.append(struct.unpack(">II", head[start : start + 8]))
    return max(sizes, key=lambda size: size[0] * size[1]) if sizes else None


_SVG_TAG = re.compile(rb"<svg\b[^>]*>", re.S)
_ATTR = re.compile(rb'\s(width|height|viewBox)\s*=\s*["\']([^"\']*)["\']')
_LENGTH = re.compile(rb"^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$")


def _svg_size(head: bytes) -> tuple[int, int] | None:
    """From width and height in pixels, else from the viewBox."""
    tag = _SVG_TAG.search(head)
    if tag is None:
        return None
    attrs = {name: value for name, value in _ATTR.findall(tag.group())}
    width, height = (_LENGTH.match(attrs.get(name, b"")) for name in (b"width", b"height"))
    if width and height:
        return _whole(width.group(1)), _whole(height.group(1))
    box = attrs.get(b"viewBox", b"").replace(b",", b" ").split()
    if len(box) == 4:
        return _whole(box[2]), _whole(box[3])
    return None


def _whole(number: bytes) -> int:
    """A dimension rounded to whole pixels; 0 for anything that is not a finite number."""
    try:
        value = float(number)
    except ValueError:
        return 0
    return round(value) if math.isfinite(value) else 0


MAX_DIMENSION = 1_000_000
"""Larger widths or heights are taken as nonsense (and would not fit the database)."""


def _plausible(size: tuple[int, int] | None) -> tuple[int, int] | None:
    if size is None or not all(0 < side <= MAX_DIMENSION for side in size):
        return None
    return size


class _RangedFile(io.RawIOBase):
    """A read-only file whose bytes are fetched on demand, in blocks, by ``read``."""

    BLOCK = HEADER_BYTES
    MAX_BLOCKS = 16
    """At most 1 MiB is read: a header that needs more is treated as having no size."""

    def __init__(self, read: Callable[[int, int], bytes], head: bytes) -> None:
        self._read = read
        self._blocks: dict[int, bytes] = {0: head}
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._position = offset
        elif whence == io.SEEK_CUR:
            self._position += offset
        else:
            raise OSError("seeking from the end is not supported")
        return self._position

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        wanted = len(buffer)
        got = b""
        while len(got) < wanted:
            index, start = divmod(self._position + len(got), self.BLOCK)
            if index not in self._blocks:
                if len(self._blocks) >= self.MAX_BLOCKS:
                    raise OSError("the header is spread too far through the file")
                self._blocks[index] = self._read(index * self.BLOCK, self.BLOCK)
            piece = self._blocks[index][start : start + wanted - len(got)]
            if not piece:
                break  # end of file
            got += piece
        buffer[: len(got)] = got
        self._position += len(got)
        return len(got)
