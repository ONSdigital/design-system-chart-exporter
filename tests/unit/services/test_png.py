import pytest

from app.domain.exceptions import RenderError
from app.services.png import read_png_dimensions
from tests.helpers import PNG_SIGNATURE
from tests.helpers import make_png_bytes as make_png_header


def test_reads_dimensions_from_ihdr():
    assert read_png_dimensions(make_png_header(1200, 640)) == (1200, 640)


def test_reads_dimensions_at_scale():
    assert read_png_dimensions(make_png_header(2400, 1280)) == (2400, 1280)


def test_rejects_non_png_bytes():
    with pytest.raises(RenderError, match="bad signature"):
        read_png_dimensions(b"GIF89a" + b"\x00" * 30)


def test_rejects_truncated_data():
    with pytest.raises(RenderError, match="bad signature"):
        read_png_dimensions(PNG_SIGNATURE)


def test_rejects_missing_ihdr_chunk():
    data = PNG_SIGNATURE + b"\x00\x00\x00\r" + b"XXXX" + b"\x00" * 13
    with pytest.raises(RenderError, match="IHDR"):
        read_png_dimensions(data)


def test_rejects_zero_dimensions():
    with pytest.raises(RenderError, match="zero width or height"):
        read_png_dimensions(make_png_header(0, 640))


def test_accepts_the_minimal_24_byte_header():
    """Signature + length + IHDR + width + height is exactly 24 bytes: the parser needs nothing more."""
    assert read_png_dimensions(make_png_header(10, 20)[:24]) == (10, 20)


def test_rejects_23_bytes():
    with pytest.raises(RenderError, match="bad signature"):
        read_png_dimensions(make_png_header()[:23])


@pytest.mark.parametrize("chunk_type", [b"AAAA", b"ZZZZ", b"IHDS", b"ihdr"])
def test_rejects_wrong_chunk_type_whatever_it_sorts_as(chunk_type):
    """The IHDR check is an equality check, not an ordering one."""
    data = PNG_SIGNATURE + b"\x00\x00\x00\r" + chunk_type + b"\x00" * 13

    with pytest.raises(RenderError, match="IHDR"):
        read_png_dimensions(data)


def test_rejects_zero_height():
    with pytest.raises(RenderError, match="zero width or height"):
        read_png_dimensions(make_png_header(1200, 0))


def test_accepts_one_by_one_pixel():
    assert read_png_dimensions(make_png_header(1, 1)) == (1, 1)
