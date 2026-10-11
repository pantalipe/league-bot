import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from league_bot.slayer.status import DailyStatusStore, DailyStatusError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "daily.json"
        self.now = datetime(2026, 10, 10, 1, 59, tzinfo=ZoneInfo("America/Sao_Paulo"))
        self.store = DailyStatusStore(self.path, now=lambda: self.now)

    def test_reset_at_two_preserves_named_quotas_and_history(self):
        self.store.mark_progress("mission:cubo-de-melhora", 3)
        self.store.mark_progress("mission:outra", 1, 2, label="Outra")
        self.assertEqual(self.store.snapshot()["cycle_id"], "2026-10-09")
        self.now = self.now.replace(hour=2, minute=0)
        state = self.store.snapshot()
        self.assertEqual(state["cycle_id"], "2026-10-10")
        self.assertEqual(state["tasks"]["mission:outra"]["target"], 2)
        self.assertEqual(state["tasks"]["mission:cubo-de-melhora"]["status"], "not_checked")
        self.assertEqual(state["history"][0]["tasks"]["mission:cubo-de-melhora"]["progress"], 3)
        self.assertIn("T02:00:00-03:00", state["next_reset"])

    def test_persistence_and_stale_result(self):
        self.store.mark_progress("summon_sword", 2)
        self.assertEqual(DailyStatusStore(self.path, now=lambda: self.now).snapshot()["tasks"]["summon_sword"]["progress"], 2)
        old = self.store.cycle_id()
        self.now = self.now.replace(hour=2)
        self.store.mark_progress("attendance", 1, expected_cycle=old)
        self.assertEqual(self.store.snapshot()["tasks"]["attendance"]["progress"], 0)

    def test_invalid_counts_leave_bytes_unchanged(self):
        self.store.snapshot()
        before = self.path.read_bytes()
        for value, target in [(True, 3), (-1, 3), (4, 3), (1, 0), (1, 10001)]:
            with self.assertRaises(ValueError):
                self.store.mark_progress("summon_sword", value, target)
            self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_state_preserved(self):
        for content in ['bad json', '{}', '[]', '{"schema_version":1,"tasks":{},"history":[],"cycle_id":"invalid"}']:
            self.path.write_text(content)
            with self.assertRaises(DailyStatusError):
                self.store.snapshot()
            self.assertEqual(self.path.read_text(), content)

    def test_parallel_writes_keep_each_named_task(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.store.mark_progress(f"mission:{i}", 1, 3), range(20)))
        self.assertTrue(all(self.store.snapshot()["tasks"][f"mission:{i}"]["progress"] == 1 for i in range(20)))

    def test_failure_preserves_verified_completion(self):
        self.store.mark_progress("attendance", 1, source="visual")
        task = self.store.mark_error("attendance", "navigation failed")["tasks"]["attendance"]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["source"], "visual")
        self.assertEqual(task["last_error"], "navigation failed")

    def test_history_bounded_without_fabricating_skipped_days(self):
        for day in range(1, 25):
            self.now = self.now.replace(day=day, hour=3)
            self.store.snapshot()
        self.assertEqual(len(self.store.snapshot()["history"]), 14)


if __name__ == "__main__":
    unittest.main()
