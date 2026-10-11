from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

try:
    from tests import slayer_compat as la
    if not la.available():
        raise ImportError('league_bot unavailable')
    from league_bot.macro import MacroError
    from league_bot.imaging import Frame
except ImportError as exc:
    from unittest import SkipTest
    raise SkipTest('league_bot nao encontrado (LEAGUE_BOT_DIR)') from exc

from league_bot.slayer.diamonds import _frame_image, parse_diamond_text, read_diamonds


class DiamondTextTests(unittest.TestCase):
    def test_parses_plain_and_grouped_balances(self):
        for text, expected in [('999', 999), ('1,000', 1000), ('16,027', 16027)]:
            with self.subTest(text=text):
                self.assertEqual(parse_diamond_text(text), expected)

    def test_rejects_incomplete_or_ambiguous_ocr(self):
        for text in ['', 'unreadable', '1,27', '1,000K', '1.000', '-100', '100 diamonds', '1 000']:
            with self.subTest(text=text), self.assertRaises(MacroError):
                parse_diamond_text(text)

    def test_rejects_wrong_dimensions_and_corrupt_buffer(self):
        with self.assertRaises(MacroError):
            _frame_image(Frame(320, 240, bytes(320 * 3 * 240)))
        with self.assertRaises(MacroError):
            _frame_image(SimpleNamespace(width=434, height=810, bgr=b''))

    def test_converts_bgr_frame_to_top_down_rgb(self):
        width, height = 434, 810
        stride = ((width * 3 + 3) // 4) * 4
        pixels = bytearray(stride * height)
        # league_bot stores bottom-up BGR; set the first pixel on two rows.
        pixels[(height - 1) * stride:(height - 1) * stride + 3] = bytes((0, 0, 255))
        pixels[(height - 2) * stride:(height - 2) * stride + 3] = bytes((255, 0, 0))
        image = _frame_image(Frame(width, height, bytes(pixels)))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(image.getpixel((0, 1)), (0, 0, 255))

    @mock.patch('league_bot.slayer.diamonds.read_header_digits')
    def test_unreadable_or_damaged_header_fails_closed(self, read):
        # A black frame has no cyan diamond icon and must never read digits.
        width, height = 434, 810
        stride = ((width * 3 + 3) // 4) * 4
        frame = Frame(width, height, bytes(stride * height))
        with self.assertRaises(MacroError):
            read_diamonds(frame)
        read.assert_not_called()

    def test_all_calibrated_headers_through_full_frame_reader(self):
        for path in (ROOT / 'tests/fixtures/slayer/diamonds').glob('*.png'):
            expected = int(path.stem.rsplit('-', 1)[-1])
            image = Image.new('RGB', (434, 810))
            with Image.open(path) as header:
                image.paste(header, (252, 49))
            image.paste((0, 160, 220), (241, 51, 251, 70))
            stride = ((434 * 3 + 3) // 4) * 4
            pixels = bytearray(stride * 810)
            for y in range(810):
                line = image.crop((0, y, 434, y + 1)).tobytes('raw', 'BGR')
                offset = (809 - y) * stride
                pixels[offset:offset + len(line)] = line
            with self.subTest(path=path.name):
                self.assertEqual(read_diamonds(Frame(434, 810, bytes(pixels))), expected)


if __name__ == '__main__':
    unittest.main()
