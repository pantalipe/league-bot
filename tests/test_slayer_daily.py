"""Focused coverage for the home bot's mandatory attendance daily runner."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la

if la.available():
    from league_bot.daily import DailyBusy, DailyError
    from league_bot.game import GameError
    from league_bot.macro import MacroError
    from league_bot.slayer.daily import ATTENDANCE_MACRO, HomeDailyResult, HomeDailyRunner


class FakeEntries:
    def __init__(self, macros=(), missing=(), last_order=()):
        self.items = list(macros)
        self.missing_items = list(missing)
        self.previous = list(last_order)
        self.recorded = None
        self.added = []
        self.removed = []

    def macros(self):
        return list(self.items)

    def missing(self):
        return list(self.missing_items)

    def last_order(self):
        return list(self.previous)

    def record_run(self, order, when):
        self.recorded = (tuple(order), when)

    def add(self, name):
        self.added.append(name)

    def remove(self, name):
        self.removed.append(name)


class FakeGame:
    def __init__(self, attendance="claimed", *, attendance_error=None, macro_error=None, screenshot_error=None):
        self.attendance = attendance
        self.attendance_error = attendance_error
        self.macro_error = macro_error
        self.screenshot_error = screenshot_error
        self.calls = []

    def start(self):
        self.calls.append("start")

    def check_attendance(self):
        self.calls.append("attendance")
        if self.attendance_error:
            raise self.attendance_error
        return self.attendance

    def run_macro(self, name):
        self.calls.append(name)
        if self.macro_error:
            raise self.macro_error

    def cancel(self):
        self.calls.append("cancel")

    def screenshot(self):
        self.calls.append("screenshot")
        if self.screenshot_error:
            raise self.screenshot_error
        return "frame"


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class HomeDailyRunnerTests(unittest.TestCase):
    def make_runner(self, macros=(), **game_kwargs):
        entries, game = FakeEntries(macros), FakeGame(**game_kwargs)
        runner = HomeDailyRunner(game, entries, now=lambda: datetime(2026, 10, 10))
        return runner, entries, game

    def test_empty_daily_runs_attendance_only(self):
        runner, entries, game = self.make_runner()
        result = runner.run()
        self.assertEqual(result.order, (ATTENDANCE_MACRO,))
        self.assertEqual(result.done, (ATTENDANCE_MACRO,))
        self.assertEqual(result.attendance, "claimed")
        self.assertEqual(game.calls, ["start", "attendance", "screenshot"])
        self.assertEqual(entries.recorded[0], (ATTENDANCE_MACRO,))
        self.assertEqual(runner.macros(), [ATTENDANCE_MACRO])

    def test_attendance_is_first_and_other_macros_are_shuffled_and_announced(self):
        runner, entries, game = self.make_runner(["a", "b", "c"])
        announced = []
        result = runner.run(announced.append)
        self.assertEqual(result.order[0], ATTENDANCE_MACRO)
        self.assertEqual(set(result.order[1:]), {"a", "b", "c"})
        self.assertEqual(announced, [result.order])
        self.assertEqual(game.calls[1], "attendance")
        self.assertEqual(game.calls[2:-1], list(result.order[1:]))
        self.assertEqual(entries.recorded[0], result.order)

    def test_already_claimed_outcome_is_returned(self):
        runner, _, _ = self.make_runner(attendance="already_claimed")
        self.assertEqual(runner.run().attendance, "already_claimed")

    def test_attendance_failure_stops_user_macros(self):
        runner, _, game = self.make_runner(["a"], attendance_error=MacroError("attendance failed"))
        result = runner.run()
        self.assertEqual(result.status, "failed")
        self.assertIsNone(result.attendance)
        self.assertNotIn("a", game.calls)

    def test_user_macro_failure_is_reported_after_attendance(self):
        runner, _, game = self.make_runner(["a"], macro_error=GameError("macro failed"))
        result = runner.run()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.attendance, "claimed")
        self.assertIn(ATTENDANCE_MACRO, result.done)
        self.assertNotIn("b", game.calls)

    def test_busy_runner_is_refused(self):
        runner, _, game = self.make_runner()
        self.assertTrue(runner._lock.acquire(blocking=False))
        try:
            with self.assertRaises(DailyBusy):
                runner.run()
        finally:
            runner._lock.release()
        self.assertEqual(game.calls, [])

    def test_cancel_during_attendance_prevents_user_macros(self):
        runner, _, game = self.make_runner(["a"])

        def cancel_from_attendance():
            game.calls.append("attendance")
            runner.cancel()
            raise la.league_bot.macro.MacroCancelled("cancelled")

        game.check_attendance = cancel_from_attendance
        result = runner.run()
        self.assertEqual(result.status, "cancelled")
        self.assertNotIn("a", game.calls)

    def test_screenshot_failure_does_not_change_completed_result(self):
        runner, _, _ = self.make_runner(screenshot_error=OSError("no frame"))
        result = runner.run()
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.frame)

    def test_mandatory_attendance_cannot_be_added_or_removed(self):
        runner, entries, _ = self.make_runner()
        with self.assertRaises(DailyError):
            runner.add(ATTENDANCE_MACRO)
        with self.assertRaises(DailyError):
            runner.remove(ATTENDANCE_MACRO)
        self.assertEqual((entries.added, entries.removed), ([], []))

    def test_missing_user_macro_blocks_all_actions(self):
        runner, _, game = self.make_runner(["gone"])
        runner._entries.missing_items = ["gone"]
        with self.assertRaises(DailyError):
            runner.run()
        self.assertEqual(game.calls, [])


if __name__ == "__main__":
    unittest.main()
