"""Regression coverage for recognized Guild navigation and legacy shop macro replacement."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from test_slayer_attendance import FakeBackend, FakeTime, png_frame

if la.available():
    from league_bot.imaging import solid_frame
    from league_bot.macro import MacroError, MacroRunner
    from league_bot.screens import matching_screens
    from league_bot.slayer.guild_navigation import guild_entry_step, load_profiles, prepare_guild_shop
    from league_bot.slayer.guild_navigation import _guild_profile


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "guild_navigation"
WIDTH, HEIGHT = 434, 810


def frame(name):
    return png_frame(FIXTURES / f"{name}.png")


def repeated(name, count=2):
    return [frame(name) for _ in range(count)]


def old_shop_steps():
    """The recorded prefix through the wait immediately before the Free guard."""
    return [
        {"action": "wait_window", "timeout": 30},
        {"action": "wait_for_pixel", "x": "74.08%", "y": "97.35%", "color": [82, 72, 30]},
        {"action": "click", "x": "74.08%", "y": "97.35%"},
        {"action": "wait", "seconds": 2.1},
        {"action": "wait_for_pixel", "x": "62.56%", "y": "12.78%", "color": [43, 34, 30]},
        {"action": "click", "x": "62.56%", "y": "12.78%"},
        {"action": "wait", "seconds": 1.6},
        {"action": "wait_for_pixel", "x": "53.8%", "y": "96.6%", "color": [86, 47, 6]},
        {"action": "click", "x": "53.8%", "y": "96.6%"},
        {"action": "wait", "seconds": 2.6},
        {"action": "wait_for_pixel", "x": "63.94%", "y": "38.83%", "color": [255, 196, 89]},
        {"action": "click", "x": "63.94%", "y": "38.83%"},
        {"action": "wait", "seconds": 1.9},
        {"action": "wait_for_pixel", "x": "49.19%", "y": "59.81%", "color": [151, 150, 147]},
        {"action": "click", "x": "49.19%", "y": "59.81%"},
    ]


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class GuildNavigationProfilesTests(unittest.TestCase):
    def test_sanitized_navigation_fixtures_are_unique_and_account_independent(self):
        profiles = load_profiles()
        screens = [*profiles["maps"], profiles["guild_shop"], _guild_profile()]
        self.assertEqual(matching_screens(frame("map_adventure"), screens), ["guild_map_adventure"])
        self.assertEqual(matching_screens(frame("map_dungeon"), screens), ["guild_map_dungeon"])
        self.assertEqual(matching_screens(frame("guild_shop"), screens), ["guild_shop"])
        self.assertEqual(matching_screens(frame("guild_lobby"), screens), ["guild_lobby"])
        self.assertEqual(matching_screens(solid_frame(WIDTH, HEIGHT, (0, 0, 0)), screens), [])
        home_dir = ROOT / "tests" / "fixtures" / "slayer" / "home"
        for path in home_dir.glob("*.png"):
            # These two are real modern Adventure/Dungeon map states.
            if path.name in {"adventure.png", "dungeon.png"}:
                continue
            with self.subTest(home_view=path.name):
                self.assertEqual(matching_screens(png_frame(path), profiles["maps"]), [])
        cube_dir = ROOT / "tests" / "fixtures" / "slayer" / "cube"
        for path in cube_dir.glob("*.png"):
            with self.subTest(older_cube_view=path.name):
                expected = ["guild_map_dungeon"] if path.name == "dungeon.png" else []
                self.assertEqual(matching_screens(png_frame(path), profiles["maps"]), expected)

    def test_entry_step_only_clicks_guild_after_recognizing_either_map_variant(self):
        for map_state in ("map_adventure", "map_dungeon"):
            with self.subTest(map_state=map_state):
                time = FakeTime()
                backend = FakeBackend(repeated(map_state) + repeated("guild_lobby"))
                runner = MacroRunner(backend, "Slayer Legend", foreground=False,
                                    sleep=time.sleep, clock=time.clock)
                runner.run([guild_entry_step()])
                self.assertEqual(backend.click_log, [(293, 110, False)])

    def test_entry_retries_one_missed_adventure_navigation_click(self):
        time = FakeTime()
        main = png_frame(ROOT / 'tests/fixtures/slayer/home/main.png')
        backend = FakeBackend([main] * 14 + repeated('map_dungeon') + repeated('guild_lobby'))
        runner = MacroRunner(backend, 'Slayer Legend', foreground=False,
                            sleep=time.sleep, clock=time.clock)
        runner.run([guild_entry_step()])
        self.assertEqual(backend.click_log, [(331,784,False), (331,784,False), (293,110,False)])

    def test_unknown_map_times_out_without_guessing_a_guild_click(self):
        time = FakeTime()
        backend = FakeBackend([solid_frame(WIDTH, HEIGHT, (0, 0, 0))])
        runner = MacroRunner(backend, "Slayer Legend", foreground=False,
                            sleep=time.sleep, clock=time.clock)
        step = guild_entry_step()
        step["timeout"] = 0.6
        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            runner.run([step])
        self.assertEqual(backend.click_log, [])

    def test_pet_reuses_shared_guild_entry_before_opening_its_modal(self):
        from league_bot.slayer.pet import PetRunner
        pet_dir = ROOT / "tests" / "fixtures" / "slayer" / "pet"
        time = FakeTime()
        backend = FakeBackend(repeated("map_adventure") + repeated("guild_lobby") * 2 +
                              [png_frame(pet_dir / "pet_0.png")] * 2)
        runner = PetRunner(backend, "Slayer Legend", foreground=False,
                           sleep=time.sleep, clock=time.clock)
        runner._enter(7)
        self.assertEqual(backend.click_log, [(293, 110, False), (181, 773, False)])

    def test_prepare_replaces_only_the_known_navigation_prefix(self):
        steps = old_shop_steps()
        tail = copy.deepcopy(steps[10:])
        result = prepare_guild_shop(steps)
        self.assertEqual(result[0]["action"], "screen_flow")
        self.assertEqual(result[0]["terminal"], "guild_shop")
        self.assertEqual(result[1:], tail)
        screens = {screen["name"]: screen for screen in result[0]["screens"]}
        self.assertEqual(screens["guild_map_adventure"]["click"], {"x": 293, "y": 110})
        self.assertEqual(screens["guild_map_dungeon"]["click"], {"x": 293, "y": 110})
        self.assertEqual(screens["guild_lobby"]["click"], {"x": 234, "y": 775})
        self.assertEqual(screens["guild_lobby"]["max_clicks"], 2)
        self.assertEqual(screens["guild_lobby"]["retry_after_seconds"], 3.0)
        self.assertEqual(result[1]["color"], [255, 196, 89])
        self.assertEqual(result[2]["x"], "63.94%")

    def test_shop_entry_retries_one_unresponsive_guild_click_after_delay(self):
        time = FakeTime()
        steps = prepare_guild_shop(old_shop_steps())
        backend = FakeBackend(repeated("map_adventure") + [frame("guild_lobby")] * 14 +
                              repeated("guild_shop"))
        runner = MacroRunner(backend, "Slayer Legend", foreground=False,
                            sleep=time.sleep, clock=time.clock)
        runner.run([steps[0]])
        self.assertEqual(backend.click_log, [
            (293, 110, False), (234, 775, False), (234, 775, False),
        ])

    def test_unrecognized_recording_does_not_get_rewritten(self):
        steps = old_shop_steps()
        steps[5]["x"] = "62.57%"
        self.assertEqual(prepare_guild_shop(steps), steps)


if __name__ == "__main__":
    unittest.main()
