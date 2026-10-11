"""Tracking integration: visual proof, partial failures and cycle boundaries."""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tests import slayer_compat as la
from league_bot.slayer.status import DailyStatusStore
from test_slayer_daily import FakeEntries, FakeGame

if la.available():
    from league_bot.macro import MacroError
    from league_bot.slayer.daily import HomeDailyRunner


@unittest.skipUnless(la.available(), "league_bot unavailable")
class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = datetime(2026, 10, 10, 1, 59, tzinfo=ZoneInfo("America/Sao_Paulo"))
        self.path = Path(self.tmp.name) / "status.json"
        self.store = DailyStatusStore(self.path, now=lambda: self.clock)

    def game(self, logs, error=None):
        settings = la.load_settings(environ={}, env_file=None)
        game = la.HomeSlayerGame(settings, backend=object(), status_store=self.store)
        def run(*args):
            for message in logs:
                game._log(message)
            if error:
                raise error
        game._run_steps = run
        return game

    def test_clicking_claim_alone_is_not_confirmation(self):
        game = self.game(["screen 'attendance_claim_ready' clicked"])
        self.assertTrue(game._run_observed_steps([], "start", "game"))
        self.assertEqual(self.store.snapshot()["tasks"]["attendance"]["progress"], 0)

    def test_confirmed_claim_persists_even_if_navigation_later_fails(self):
        game = self.game(["screen 'attendance_claimed_settings' clicked"], MacroError("navigation failed"))
        with self.assertRaises(MacroError):
            game._run_observed_steps([], "check", "game")
        task = DailyStatusStore(self.path, now=lambda: self.clock).snapshot()["tasks"]["attendance"]
        self.assertEqual(task["progress"], 1)
        self.assertEqual(task["status"], "completed")

    def test_daily_records_attendance_and_failed_macro_separately(self):
        game = FakeGame(macro_error=MacroError("failed"))
        runner = HomeDailyRunner(game, FakeEntries(["cubo"]), status_store=self.store)
        result = runner.run()
        self.assertEqual(result.status, "failed")
        tasks = self.store.snapshot()["tasks"]
        self.assertEqual(tasks["attendance"]["progress"], 1)
        self.assertEqual(tasks["macro:cubo"]["status"], "error")
        self.assertEqual(tasks["mission:cubo-de-melhora"]["progress"], 0)

    def test_run_crossing_reset_does_not_complete_new_cycle(self):
        game = FakeGame()
        def check():
            self.clock = datetime(2026, 10, 10, 2, 1, tzinfo=ZoneInfo("America/Sao_Paulo"))
            return "already_claimed"
        game.check_attendance = check
        HomeDailyRunner(game, FakeEntries(), status_store=self.store).run()
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["cycle_id"], "2026-10-10")
        self.assertEqual(snapshot["tasks"]["attendance"]["progress"], 0)


if __name__ == "__main__":
    unittest.main()
