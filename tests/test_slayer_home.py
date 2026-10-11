"""Fixture-backed checks for safe recovery to Slayer's recognized home screen."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
if la.available():
    from league_bot.imaging import solid_frame
    from league_bot.macro import MacroCancelled, MacroError, MacroRunner
    from league_bot.screens import matching_screens
    from league_bot.slayer.home import home_step, load_screens

from test_slayer_attendance import FakeBackend, FakeTime, png_frame

WIDTH, HEIGHT = 434, 810
FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "home"


def frame(name):
    return png_frame(FIXTURES / f"{name}.png")


def repeated(*states):
    return [frame(state) for state in states for _ in range(2)]


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class HomeRecoveryProfileTests(unittest.TestCase):
    def test_sanitized_fixtures_match_only_their_home_recovery_state(self):
        screens = load_screens()
        expected = {
            "main": ["main"],
            "adventure": ["adventure_map"],
            # The dungeon fixture is already the adventure map with its active
            # bottom navigation; the shelter's red arrow returns to that map.
            "dungeon": ["adventure_map"],
            "rift_free": ["red_back_panel"],
            "rift_exhausted": ["red_back_panel"],
            "shelter": ["red_back_panel"],
            "multiplier": ["multiplier_back"],
        }
        for fixture, names in expected.items():
            with self.subTest(fixture=fixture):
                self.assertEqual(matching_screens(frame(fixture), screens), names)

    def test_home_step_is_bounded_and_uses_main_as_terminal(self):
        step = home_step()
        self.assertEqual((step["action"], step["terminal"], step["timeout"],
                          step["stable_frames"], step["frame_size"]),
                         ("screen_flow", "main", 40, 2, [WIDTH, HEIGHT]))
        screens = {screen["name"]: screen for screen in step["screens"]}
        self.assertEqual(screens["adventure_map"]["click"], {"x": 325, "y": 784})
        self.assertEqual(screens["red_back_panel"]["click"], {"x": 45, "y": 775})
        self.assertEqual(screens["multiplier_back"]["click"], {"x": 45, "y": 775})
        self.assertNotIn("click", screens["main"])


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class HomeRecoveryFlowTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.backend = FakeBackend()
        self.runner = MacroRunner(
            self.backend, "Slayer Legend", foreground=False,
            sleep=self.time.sleep, clock=self.time.clock,
        )

    def run_recovery(self, *, timeout=6):
        step = home_step()
        step["timeout"] = timeout
        self.runner.run([step])

    def test_shelter_back_to_dungeon_then_map_to_main(self):
        self.backend.frames = repeated("shelter", "dungeon", "adventure", "main")

        self.run_recovery()

        self.assertEqual(self.backend.click_log, [(45, 775, False), (325, 784, False)])

    def test_pet_panel_closes_and_returns_from_guild_without_cleaning(self):
        pet_dir = ROOT / "tests/fixtures/slayer/pet"
        self.backend.frames = [png_frame(pet_dir / "pet_1.png")]*2 + [png_frame(pet_dir / "guild.png")]*2 + repeated("dungeon", "main")
        self.run_recovery()
        self.assertEqual(self.backend.click_log, [(217,746,False),(52,777,False),(325,784,False)])

    def test_startup_keeps_pet_close_recovery_and_attendance_claim(self):
        settings = la.load_settings(environ={},env_file=None)
        game = la.HomeSlayerGame(settings,object())
        flows = [s for s in game.load_macro_steps("start_game_recognized") if s["action"] == "screen_flow"]
        names = {s["name"] for flow in flows for s in flow["screens"]}
        self.assertIn("home_close_pet",names)
        self.assertIn("home_return_guild",names)
        self.assertIn("attendance_claim_ready",names)
        self.assertNotIn("home_close_attendance_claim_ready",names)

    def test_rift_free_and_paid_states_only_back_out_without_enter_or_multiplier(self):
        for rift_state in ("rift_free", "rift_exhausted"):
            with self.subTest(rift_state=rift_state):
                self.backend = FakeBackend(repeated(rift_state, "adventure", "main"))
                self.runner = MacroRunner(
                    self.backend, "Slayer Legend", foreground=False,
                    sleep=self.time.sleep, clock=self.time.clock,
                )

                self.run_recovery()

                self.assertEqual(self.backend.click_log, [(45, 775, False), (325, 784, False)])
                self.assertNotIn((230, 664, False), self.backend.click_log)  # free entry
                self.assertNotIn((346, 584, False), self.backend.click_log)  # x3 multiplier

    def test_multiplier_overlay_uses_only_its_single_back_action(self):
        self.backend.frames = repeated("multiplier", "rift_exhausted", "adventure", "main")

        self.run_recovery()

        self.assertEqual(self.backend.click_log, [
            (45, 775, False), (45, 775, False), (325, 784, False),
        ])
        self.assertNotIn((230, 664, False), self.backend.click_log)
        self.assertNotIn((346, 584, False), self.backend.click_log)

    def test_unknown_and_transient_frames_do_not_trigger_extra_clicks(self):
        unknown = solid_frame(WIDTH, HEIGHT, (0, 0, 0))
        self.backend.frames = repeated("multiplier") + [unknown, unknown] + repeated("main")

        self.run_recovery()

        self.assertEqual(self.backend.click_log, [(45, 775, False)])

    def test_unknown_frames_time_out_without_clicking(self):
        self.backend.frames = [solid_frame(WIDTH, HEIGHT, (0, 0, 0))]
        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            self.run_recovery(timeout=1)
        self.assertEqual(self.backend.click_log, [])

    def test_persistent_multiplier_panel_gets_only_its_bounded_back_click(self):
        self.backend.frames = [frame("multiplier")] * 80

        with self.assertRaisesRegex(MacroError, "timed out.*multiplier_back"):
            self.run_recovery(timeout=5)

        self.assertEqual(self.backend.click_log, [(45, 775, False)])

    def test_cancel_after_back_click_stops_without_followup_actions(self):
        self.backend.frames = repeated("shelter", "dungeon", "adventure", "main")
        capture = self.backend.capture

        def cancel_after_first_back(hwnd):
            if self.backend.click_log:
                raise MacroCancelled("test cancellation after first back")
            return capture(hwnd)

        with mock.patch.object(self.backend, "capture", side_effect=cancel_after_first_back):
            with self.assertRaises(MacroCancelled):
                self.run_recovery()

        self.assertEqual(self.backend.click_log, [(45, 775, False)])

    def test_existing_window_startup_recovers_shelter_then_places_and_minimizes(self):
        self.backend = FakeBackend(repeated("shelter", "dungeon", "adventure", "main"))
        self.time = FakeTime()
        launches = []
        settings = SimpleNamespace(
            window_title="Slayer Legend", start_macro="start_game_recognized",
            foreground_input=False, macros_dir=Path(tempfile.gettempdir()) / "slayer-home-tests",
            data_dir=Path(tempfile.gettempdir()) / "slayer-home-test-data",
            process_names=("SlayerLegend.exe",),
        )
        game = la.HomeSlayerGame(
            settings, self.backend,
            launcher=lambda _settings: launches.append("launch"),
            runner_factory=lambda backend, title, foreground, log: MacroRunner(
                backend, title, foreground, log, sleep=self.time.sleep, clock=self.time.clock,
            ),
        )
        base_steps = [home_step(), {"action": "minimize"}]

        with mock.patch.object(la.SlayerGame, "load_macro_steps", return_value=base_steps):
            result = game.start()

        self.assertIn("pronto", result)
        self.assertEqual(launches, [])
        self.assertEqual(self.backend.click_log, [(45, 775, False), (325, 784, False)])
        self.assertIn(("move_resize", 1460, 202, 438, 814), self.backend.calls)
        self.assertEqual(self.backend.calls[-1], ("minimize",))


if __name__ == "__main__":
    unittest.main()
