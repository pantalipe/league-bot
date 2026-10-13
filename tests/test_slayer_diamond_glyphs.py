from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

try:
    from tests import slayer_compat as la
    if not la.available():
        raise ImportError("league_bot unavailable")
    from league_bot.macro import MacroError
except ImportError as exc:
    from unittest import SkipTest
    raise SkipTest("league_bot nao encontrado (LEAGUE_BOT_DIR)") from exc

from league_bot.slayer.diamond_glyphs import load_glyph_templates, read_header_digits

FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "diamonds"


class SlayerDiamondGlyphTests(unittest.TestCase):
    def test_every_digit_has_a_manually_labelled_template(self):
        self.assertEqual(set(load_glyph_templates()), set("0123456789"))

    def test_recorded_header_crops_match_their_visual_balance(self):
        expected = {
            "pet-before-16027.png": 16027,
            "pet-after-15027.png": 15027,
            "header-9647.png": 9647,
            "header-2827.png": 2827,
            "header-1317.png": 1317,
            "header-1517.png": 1517,
            "header-1267.png": 1267,
            "header-1467.png": 1467,
            "header-1617.png": 1617,
            "header-1667.png": 1667,
            "header-live-5259.png": 5259,
            "header-live-11259.png": 11259,
            "header-live-11159.png": 11159,
            "header-live-13799.png": 13799,
        }
        for filename, balance in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(read_header_digits(Image.open(FIXTURES / filename)), balance)

    def test_live_header_additions_still_reject_unlabelled_ink(self):
        for filename in ("header-live-11259.png", "header-live-11159.png",
                         "header-live-13799.png"):
            with self.subTest(filename=filename):
                image = Image.open(FIXTURES / filename).convert("RGB")
                image.putpixel((45, 7), (255, 255, 255))
                with self.assertRaises(MacroError):
                    read_header_digits(image)

    def test_blank_header_is_unreadable(self):
        with self.assertRaises(MacroError):
            read_header_digits(Image.new("RGB", (48, 21), (0, 0, 0)))

    def test_unknown_extra_pixel_is_not_ignored(self):
        image = Image.open(FIXTURES / "pet-before-16027.png").convert("RGB")
        image.putpixel((45, 7), (255, 255, 255))
        with self.assertRaises(MacroError):
            read_header_digits(image)

    def test_grouping_comma_is_required_for_four_digit_balances(self):
        image = Image.open(FIXTURES / "header-9647.png").convert("RGB")
        for x in range(8, 13):
            image.putpixel((x, 15), (0, 0, 0))
        with self.assertRaises(MacroError):
            read_header_digits(image)

    def test_bad_crop_size_fails_closed(self):
        with self.assertRaises(MacroError):
            read_header_digits(Image.new("RGB", (47, 21), (0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
