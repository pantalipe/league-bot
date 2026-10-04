import struct
import unittest
import zlib

from league_bot.imaging import Frame, solid_frame


def frame_from_rows(rows):
    """Build a Frame from top-down rows of (R, G, B) tuples."""
    height, width = len(rows), len(rows[0])
    row_size = ((width * 3 + 3) // 4) * 4
    data = bytearray()
    for row in reversed(rows):  # BMP rows are stored bottom-up
        raw = b"".join(bytes([b, g, r]) for (r, g, b) in row)
        data += raw + b"\x00" * (row_size - len(raw))
    return Frame(width, height, bytes(data))


def decode_png(png):
    """Tiny PNG reader for 8-bit RGB / filter 0, enough to verify our encoder."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", None
    while pos < len(png):
        length, tag = struct.unpack(">I4s", png[pos:pos + 8])
        payload = png[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])[0]
        assert crc == zlib.crc32(tag + payload) & 0xFFFFFFFF
        if tag == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", payload[:10])
            assert (depth, color_type) == (8, 2)
            size = (width, height)
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + length
    width, height = size
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = []
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        assert line[0] == 0
        rows.append([tuple(line[1 + x * 3:4 + x * 3]) for x in range(width)])
    return rows


class FrameTests(unittest.TestCase):
    ROWS = [
        [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12), (13, 14, 15)],
        [(20, 21, 22), (23, 24, 25), (26, 27, 28), (29, 30, 31), (32, 33, 34)],
    ]  # width 5 -> 15 bytes per row, padded to 16

    def test_pixel_is_top_left_based_rgb(self):
        frame = frame_from_rows(self.ROWS)
        for y, row in enumerate(self.ROWS):
            for x, expected in enumerate(row):
                self.assertEqual(frame.pixel(x, y), expected)

    def test_pixel_out_of_range_is_none(self):
        frame = solid_frame(4, 3, (9, 9, 9))
        for x, y in [(-1, 0), (0, -1), (4, 0), (0, 3)]:
            self.assertIsNone(frame.pixel(x, y))

    def test_png_roundtrip_with_row_padding(self):
        frame = frame_from_rows(self.ROWS)
        self.assertEqual(decode_png(frame.to_png()), self.ROWS)

    def test_bmp_header_and_size(self):
        frame = frame_from_rows(self.ROWS)
        bmp = frame.to_bmp()
        self.assertEqual(bmp[:2], b"BM")
        self.assertEqual(struct.unpack("<I", bmp[2:6])[0], len(bmp))
        self.assertEqual(struct.unpack("<ii", bmp[18:26]), (5, 2))
        self.assertEqual(len(bmp), 54 + 16 * 2)

    def test_average_of_a_patch_is_clipped_at_the_edges(self):
        rows = [[(0, 0, 0), (100, 100, 100), (200, 200, 200)] for _ in range(3)]
        frame = frame_from_rows(rows)
        self.assertEqual(frame.average(1, 1, radius=1), (100, 100, 100))
        self.assertEqual(frame.average(0, 0, radius=1), (50, 50, 50))  # only columns 0-1 exist
        self.assertEqual(frame.average(1, 1, radius=0), (100, 100, 100))

    def test_average_outside_the_frame_is_none(self):
        self.assertIsNone(solid_frame(4, 4, (1, 2, 3)).average(9, 9))
        self.assertEqual(solid_frame(4, 4, (1, 2, 3)).average(3, 3), (1, 2, 3))

    def test_rejects_short_buffer_and_bad_dimensions(self):
        with self.assertRaises(ValueError):
            Frame(10, 10, b"\x00" * 10)
        with self.assertRaises(ValueError):
            Frame(0, 5, b"")


if __name__ == "__main__":
    unittest.main()
