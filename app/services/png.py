"""PNG dimension extraction from raw bytes.

Playwright's bounding boxes are CSS pixels — wrong whenever
device_scale_factor > 1 — so the response's width/height are read from the
PNG itself. A PNG starts with an 8-byte signature, then the IHDR chunk:
4 bytes length + 4 bytes type ("IHDR") + width and height as big-endian
uint32 at byte offsets 16-24.
"""

import struct

from app.domain.exceptions import RenderError

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_IHDR_OFFSET = 16
_MIN_LENGTH = _IHDR_OFFSET + 8


def read_png_dimensions(data: bytes) -> tuple[int, int]:
    """Return (width, height) in pixels of a PNG byte stream.

    Raises:
        RenderError: if the bytes are not a valid PNG.
    """
    if len(data) < _MIN_LENGTH or not data.startswith(_PNG_SIGNATURE):
        raise RenderError("renderer output is not a PNG (bad signature)")
    if data[12:16] != b"IHDR":
        raise RenderError("renderer output is not a valid PNG (missing IHDR chunk)")
    width, height = struct.unpack(">II", data[_IHDR_OFFSET : _IHDR_OFFSET + 8])
    if width == 0 or height == 0:
        raise RenderError("renderer output PNG has zero width or height")
    return width, height
