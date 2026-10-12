"""Recognized Quest entry and tab selection, with claim steps preserved."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from test_slayer_attendance import FakeBackend, FakeTime, png_frame, WIDTH, HEIGHT

if la.available():
    from league_bot.macro import MacroRunner
    from league_bot.screens import matching_screens
    from league_bot.slayer.quest_navigation import (
        load_profiles, prepare_quest_collection, recovery_screens,
    )


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "quest_navigation"
HOME_FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "home"


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class QuestProfileTests(unittest.TestCase):
    def test_masked_repeat_and_daily_fixtures_are_distinct_and_main_does_not_match(self):
        profiles = load_profiles()
        screens = [profiles["quest_repeat"], profiles["quest_daily"]]
        self.assertEqual(matching_screens(png_frame(FIXTURES / "quest_repeat.png"), screens),
                         ["quest_repeat"])
        self.assertEqual(matching_screens(png_frame(FIXTURES / "quest_daily.png"), screens),
                         ["quest_daily"])
        self.assertEqual(matching_screens(png_frame(HOME_FIXTURES / "main.png"), screens), [])

    def test_recovery_only_closes_recognized_quest_tabs(self):
        screens = recovery_screens()
        self.assertEqual([screen["name"] for screen in screens],
                         ["recovery_quest_repeat", "recovery_quest_daily"])
        self.assertTrue(all(screen["click"] == {"x": 390, "y": 205} for screen in screens))


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class QuestPreparationTests(unittest.TestCase):
    def stock_steps(self):
        return json.loads((ROOT / "league_bot" / "slayer" / "macros" /
                           "collect_finished_dailys.json").read_text(encoding="utf-8"))["steps"]

    def test_stock_prefix_becomes_recognized_flow_and_reward_steps_are_bytewise_equal(self):
        original = self.stock_steps()
        prepared = prepare_quest_collection(original)
        self.assertEqual(len(prepared), 1 + len(original[7:]))
        flow = prepared[0]
        self.assertEqual(flow["action"], "screen_flow")
        self.assertEqual(flow["terminal"], "quest_daily")
        profiles = {screen["name"]: screen for screen in flow["screens"]}
        self.assertEqual(profiles["main"]["click"], {"x": 412, "y": 109})
        self.assertEqual(profiles["main"]["max_clicks"], 2)
        self.assertEqual(profiles["main"]["retry_after_seconds"], 3.0)
        self.assertEqual(profiles["quest_repeat"]["click"], {"x": 95, "y": 246})
        self.assertNotIn("click", profiles["quest_daily"])
        self.assertEqual(prepared[1:], original[7:])

    def test_custom_prefix_is_untouched(self):
        custom = self.stock_steps()
        custom[2]["x"] = "94.0%"
        original = copy.deepcopy(custom)
        self.assertEqual(prepare_quest_collection(custom), original)

    def test_main_click_can_retry_then_repeat_tab_leads_to_daily(self):
        main = png_frame(HOME_FIXTURES / "main.png")
        backend = FakeBackend([main])
        time = FakeTime()
        runner = MacroRunner(backend, "Slayer Legend", foreground=True,
                             sleep=time.sleep, clock=time.clock)
        flow = prepare_quest_collection(self.stock_steps())[0]

        def observe(_frame, screens):
            names = {screen["name"] for screen in screens}
            quest_clicks = [(x, y) for x, y, _fg in backend.click_log if (x, y) == (412, 109)]
            daily_clicks = [(x, y) for x, y, _fg in backend.click_log if (x, y) == (95, 246)]
            if "main" in names and len(quest_clicks) < 2:
                return ["main"]
            if "quest_repeat" in names and not daily_clicks:
                return ["quest_repeat"]
            if "quest_daily" in names:
                return ["quest_daily"]
            return []

        with mock.patch("league_bot.macro.matching_screens", side_effect=observe):
            runner.run([flow])
        self.assertEqual(backend.click_log,
                         [(412, 109, False), (412, 109, False), (95, 246, False)])
        self.assertGreaterEqual(time.now, 3.0)

    def test_daily_already_open_skips_repeat_tab_click(self):
        main = png_frame(HOME_FIXTURES / "main.png")
        backend = FakeBackend([main])
        time = FakeTime()
        runner = MacroRunner(backend, "Slayer Legend", foreground=True,
                             sleep=time.sleep, clock=time.clock)
        flow = prepare_quest_collection(self.stock_steps())[0]

        def observe(_frame, screens):
            names = {screen["name"] for screen in screens}
            if "main" in names and not backend.click_log:
                return ["main"]
            return ["quest_daily"] if "quest_daily" in names else []

        with mock.patch("league_bot.macro.matching_screens", side_effect=observe):
            runner.run([flow])
        self.assertEqual(backend.click_log, [(412, 109, False)])


if __name__ == "__main__":
    unittest.main()
