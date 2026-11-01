"""Focused checks for the navigation-only Slayer recovery entry point."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from league_bot.imaging import solid_frame
from league_bot.macro import MacroError, MacroRunner
from league_bot.slayer.navigation_recovery import navigation_home_step, recover_home
from test_slayer_attendance import FakeBackend, FakeTime, png_frame


HOME_FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "home"
PET_FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "pet"
SHOP_FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "shop"
WIDTH, HEIGHT = 434, 810


def home_frame(name):
    return png_frame(HOME_FIXTURES / f"{name}.png")


def pet_frame(name):
    return png_frame(PET_FIXTURES / f"{name}.png")


class NavigationRecoveryTests(unittest.TestCase):
    def runner(self, frames):
        self.backend = FakeBackend(frames, size=(WIDTH, HEIGHT))
        self.time = FakeTime()
        return MacroRunner(
            self.backend, "Slayer Legend", foreground=False,
            sleep=self.time.sleep, clock=self.time.clock,
        )

    def test_default_step_is_bounded_and_contains_only_navigation_screens(self):
        step = navigation_home_step()
        names = {screen["name"] for screen in step["screens"]}
        self.assertEqual((step["action"], step["terminal"], step["timeout"],
                          step["stable_frames"], step["frame_size"]),
                         ("screen_flow", "main", 30, 2, [WIDTH, HEIGHT]))
        self.assertIn("home_close_shop", names)
        self.assertIn("home_close_equipment", names)
        self.assertIn("home_close_pet", names)
        self.assertIn("home_return_guild", names)
        self.assertIn("adventure_map", names)
        self.assertFalse(any("attendance" in name or "reward" in name or "claim" in name
                             for name in names))
        self.assertNotIn("home_confirm_summon_reward", names)
        self.assertTrue(all(screen.get("max_clicks", 1) <= 2
                            for screen in step["screens"] if screen["name"] != "main"))

    def test_pet_reward_confirmation_requires_explicit_opt_in(self):
        default_names = {screen["name"] for screen in navigation_home_step()["screens"]}
        opt_in = {screen["name"]: screen for screen in
                  navigation_home_step(include_pet_reward=True)["screens"]}
        self.assertNotIn("home_confirm_pet_reward", default_names)
        self.assertIn("home_confirm_pet_reward", opt_in)
        self.assertIn("home_confirm_pet_reward_current", opt_in)
        self.assertEqual(opt_in["home_confirm_pet_reward"]["max_clicks"], 2)

    def test_shop_recovery_closes_the_panel_and_confirms_main(self):
        runner = self.runner([
            png_frame(SHOP_FIXTURES / "recording_shop_summon.png"),
            png_frame(SHOP_FIXTURES / "recording_shop_summon.png"),
            home_frame("main"), home_frame("main"),
        ])
        recover_home(runner)
        self.assertEqual(self.backend.click_log, [(404, 784, False)])

    def test_equipment_recovery_uses_selected_tab_to_return_to_main(self):
        runner = self.runner([home_frame("equipment_accessories")] * 2 +
                             [home_frame("main")] * 2)
        recover_home(runner)
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_pet_guild_and_map_recovery_uses_only_back_navigation(self):
        runner = self.runner(
            [pet_frame("pet_1")] * 2 + [pet_frame("guild")] * 2 +
            [home_frame("dungeon")] * 2 + [home_frame("main")] * 2
        )
        recover_home(runner)
        self.assertEqual(self.backend.click_log, [
            (217, 746, False), (52, 777, False), (325, 784, False),
        ])

    def test_unknown_screen_times_out_without_guessing_a_click(self):
        runner = self.runner([solid_frame(WIDTH, HEIGHT, (0, 0, 0))])
        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            recover_home(runner, timeout=1)
        self.assertEqual(self.backend.click_log, [])

    def test_timeout_cannot_exceed_thirty_seconds(self):
        with self.assertRaises(ValueError):
            navigation_home_step(timeout=30.1)


if __name__ == "__main__":
    unittest.main()
