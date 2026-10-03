"""Pixel access and PNG/BMP encoding for captured window frames (stdlib only)."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional, Tuple

RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class Frame:
    """A captured window image in 24-bit BMP memory layout.

    ``bgr`` holds bottom-up rows of B,G,R bytes, each row padded to a multiple
    of 4 bytes -- exactly what GetDIBits returns for a 24-bit bitmap.
    """

    width: int
    height: int
    bgr: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if len(self.bgr) < self.row_size * self.height:
            raise ValueError("pixel buffer is smaller than width x height")

    @property
    def row_size(self) -> int:
        return ((self.width * 3 + 3) // 4) * 4

    def pixel(self, x: int, y: int) -> Optional[RGB]:
        """Return (R, G, B) at top-left based (x, y), or None when out of range."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        offset = (self.height - 1 - y) * self.row_size + x * 3
        b, g, r = self.bgr[offset], self.bgr[offset + 1], self.bgr[offset + 2]
        return (r, g, b)

    def to_png(self) -> bytes:
        """Encode as an 8-bit RGB PNG using only zlib/struct."""
        row_bytes = self.width * 3
        raw = bytearray()
        for y in range(self.height):
            start = (self.height - 1 - y) * self.row_size
            row = self.bgr[start:start + row_bytes]
            rgb = bytearray(row_bytes)
            rgb[0::3] = row[2::3]
            rgb[1::3] = row[1::3]
            rgb[2::3] = row[0::3]
            raw.append(0)  # PNG filter type 0 (None)
            raw.extend(rgb)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            body = tag + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b"")
        )

    def to_bmp(self) -> bytes:
        """Encode as a 24-bit BMP file."""
        pixels = self.bgr[: self.row_size * self.height]
        file_header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
        info_header = struct.pack("<IiiHHIIiiII", 40, self.width, self.height, 1, 24, 0, len(pixels), 0, 0, 0, 0)
        return file_header + info_header + pixels


def solid_frame(width: int, height: int, rgb: RGB) -> Frame:
    """Build a single-color frame (handy for tests and calibration tooling)."""
    r, g, b = rgb
    row_size = ((width * 3 + 3) // 4) * 4
    row = bytes([b, g, r]) * width + b"\x00" * (row_size - width * 3)
    return Frame(width, height, row * height)
