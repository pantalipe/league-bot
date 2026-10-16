"""Recognized companion-to-Beast navigation and recovery profiles."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from tests.fakes import FakeBackend, FakeTime

if la.available():
    from league_bot.imaging import Frame, solid_frame
    from league_bot.config import Settings
    from league_bot.macro import MacroError, MacroRunner, load_macro, matching_screens, validate_steps
    from league_bot.slayer.companion import (active_mount_screen, beast_screen, companion_screen,
                                              prepare_mount, ready_mount_screen, recovery_screens,
                                              run_mount)
    from league_bot.slayer.game import SlayerDailyGame


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "companion"
WIDTH, HEIGHT = 434, 810


def png_frame(path: Path) -> Frame:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    row_size = ((width * 3 + 3) // 4) * 4
    rgb = image.tobytes()
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        start = y * width * 3
        for offset in range(start, start + width * 3, 3):
            row.extend((rgb[offset + 2], rgb[offset + 1], rgb[offset]))
        row.extend(b"\x00" * (row_size - width * 3))
        pixels.extend(row)
    return Frame(width, height, bytes(pixels))


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class CompanionNavigationTests(unittest.TestCase):
    def test_sanitized_real_frames_recognize_companion_and_beast(self):
        companion = png_frame(FIXTURES / "companion.png")
        beast = png_frame(FIXTURES / "beast.png")
        self.assertEqual(matching_screens(companion, [companion_screen()]), ["companion_open"])
        self.assertEqual(matching_screens(beast, [beast_screen()]), ["beast_open"])

    def test_shipped_mount_entries_use_recognized_flow_and_preserve_activation_tail(self):
        for name in ("montar_besta", "beast_colletct_free"):
            with self.subTest(name=name):
                original = load_macro(ROOT / "league_bot" / "slayer" / "macros" / f"{name}.json")
                result = prepare_mount(name, original)
                self.assertEqual(result[0], original[0])
                self.assertEqual(result[1]["action"], "screen_flow")
                self.assertEqual(result[1]["terminal"], "beast_open")
                self.assertEqual([screen["name"] for screen in result[1]["screens"]],
                                 ["main", "companion_open", "active_mount", "beast_open"])
                self.assertEqual(result[1]["screens"][0]["click"], {"x": 230, "y": 790})
                self.assertEqual(result[1]["screens"][1]["click"], {"x": 132, "y": 478})
                if name == 'montar_besta':
                    self.assertEqual(result[2:], original[7:])
                else:
                    self.assertEqual(result[2]['terminal'], 'beast_shop_free')
                    self.assertEqual(result[3:], [s for s in original[11:]
                                                  if s['action'] != 'wait_for_pixel'])
                validate_steps(result)

    def test_free_beast_shop_checkpoint_excludes_paid_offer(self):
        from league_bot.slayer.companion import beast_shop_screen
        shop = png_frame(FIXTURES / 'beast_shop_free.png')
        self.assertEqual(matching_screens(shop, [beast_shop_screen(True)]), ['beast_shop_free'])
        self.assertEqual(matching_screens(solid_frame(434,810,(0,0,0)),
                                         [beast_shop_screen(True)]), [])

    def test_custom_entry_and_unrelated_macros_are_preserved(self):
        original = load_macro(ROOT / "league_bot" / "slayer" / "macros" / "montar_besta.json")
        custom = copy.deepcopy(original)
        custom[5]["x"] = "34.00%"
        self.assertEqual(prepare_mount("montar_besta", custom), custom)
        self.assertIs(prepare_mount("other_macro", original), original)

    def test_unknown_screen_times_out_without_clicking(self):
        # Use a distinct unknown frame that cannot match the Companion profile.
        from league_bot.imaging import solid_frame
        unknown = solid_frame(WIDTH, HEIGHT, (45, 47, 50))
        backend = FakeBackend(size=(WIDTH, HEIGHT))
        backend.capture = lambda _hwnd: unknown
        time = FakeTime()
        runner = MacroRunner(backend, "Slayer Legend", foreground=False,
                             sleep=time.sleep, clock=time.clock)
        flow = {"action": "screen_flow", "terminal": "beast_open", "timeout": 0.3,
                "poll_seconds": 0.1, "stable_frames": 2, "frame_size": [WIDTH, HEIGHT],
                "screens": [{"name": "companion_open", "anchors": companion_screen()["anchors"],
                             "click": {"x": 132, "y": 478}}, beast_screen()]}
        with self.assertRaisesRegex(MacroError, "timed out"):
            runner.run([flow])
        self.assertEqual(backend.clicks(), [])

    def test_beast_recovery_is_a_recognized_exit(self):
        screens = recovery_screens()
        beast = next(screen for screen in screens if screen["name"] == "home_close_beast")
        self.assertEqual(beast["click"], {"x": 41, "y": 774})
        self.assertEqual(matching_screens(png_frame(FIXTURES / "beast.png"), [beast]),
                         ["home_close_beast"])

    def test_active_mount_fixture_requires_and_matches_hunting_quota_state(self):
        frame = png_frame(FIXTURES / "active_mount.png")
        self.assertEqual(matching_screens(frame, [active_mount_screen()]), ["active_mount"])
        for filename in ("quota_zero.png", "not_hunting.png"):
            with self.subTest(filename=filename):
                self.assertEqual(matching_screens(png_frame(FIXTURES / filename),
                                                  [active_mount_screen()]), [])
        self.assertEqual(matching_screens(png_frame(FIXTURES / "ready_mount.png"),
                                          [ready_mount_screen()]), ["ready_mount"])
        self.assertEqual(matching_screens(frame, [ready_mount_screen()]), [])
        recovery = next(screen for screen in recovery_screens()
                        if screen["name"] == "home_close_active_mount")
        self.assertEqual(recovery["click"], {"x": 41, "y": 774})
        self.assertEqual(matching_screens(frame, [recovery]), ["home_close_active_mount"])

    def test_real_game_macro_loader_and_runner_skip_active_mount_activation(self):
        active = png_frame(FIXTURES / "active_mount.png")
        beast = png_frame(FIXTURES / "beast.png")
        companion = png_frame(FIXTURES / "companion.png")
        main = png_frame(ROOT / "tests" / "fixtures" / "slayer" / "home" / "main.png")
        frames = ([active] * 2 + [beast] * 2 + [companion] * 2 + [main] * 4
                  + [companion] * 2 + [beast] * 2 + [beast] + [active] * 8
                  + [beast] * 2 + [companion] * 2 + [main] * 2)
        backend = FakeBackend(size=(WIDTH, HEIGHT))

        def capture(_hwnd):
            return frames.pop(0) if len(frames) > 1 else frames[0]

        backend.capture = capture
        time = FakeTime()

        def runner_factory(target, title, foreground, log):
            return MacroRunner(target, title, foreground, log=log,
                               sleep=time.sleep, clock=time.clock)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("league_bot.slayer.calibration_global.transform",
                           side_effect=lambda step, _data_dir: step):
            settings = Settings(window_title="Slayer Legend", macros_dir=ROOT / "macros",
                                data_dir=Path(tmp))
            game = SlayerDailyGame(settings, backend, runner_factory=runner_factory)
            loaded = game.load_macro_steps("montar_besta")
            entry_index = next(i for i, step in enumerate(loaded)
                               if step.get("action") == "screen_flow"
                               and step.get("terminal") == "beast_open")
            self.assertGreater(entry_index, 1)  # Includes the shared window/home wrappers.
            result = game.run_macro("montar_besta")

        self.assertIn("sem repetir", result)
        clicks = backend.clicks()
        self.assertEqual(clicks.count((221, 774, False)), 1)
        self.assertIn((41, 774, False), clicks)
        self.assertIn((255, 784, False), clicks)

    def test_collection_macro_keeps_generic_runner_instead_of_mount_shortcut(self):
        from league_bot.game import SlayerGame
        settings = Settings(window_title="Slayer Legend", macros_dir=ROOT / "macros",
                            data_dir=ROOT / "tests")
        game = SlayerDailyGame(settings, FakeBackend(size=(WIDTH, HEIGHT)))
        with mock.patch.object(SlayerGame, "run_macro", return_value="collection") as generic, \
                mock.patch("league_bot.slayer.companion.run_mount") as mount:
            self.assertEqual(game.run_macro("beast_colletct_free"), "collection")
        generic.assert_called_once_with("beast_colletct_free")
        mount.assert_not_called()


if __name__ == "__main__":
    unittest.main()
