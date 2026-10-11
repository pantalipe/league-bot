"""Configuration migration and background recording wrappers without game input."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import slayer_compat as la
from league_bot.slayer.status import DailyStatusStore


@unittest.skipUnless(la.available(), "league_bot unavailable")
class DailyConfigurationTests(unittest.TestCase):
    def test_seed_preserves_custom_selection_and_removal(self):
        from league_bot.slayer.selection import open_home_daily
        from league_bot.slayer.plan import DEFAULT_MACROS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "daily.json").write_text('{"macros":["custom","pet_guild"]}')
            library = SimpleNamespace(find=lambda name: True)
            local = root / "home.json"
            entries = open_home_daily(SimpleNamespace(data_dir=root), library, path=local)
            self.assertEqual(set(entries.macros()), set(DEFAULT_MACROS) | {"custom"})
            entries.remove("blorb")
            self.assertNotIn("blorb", open_home_daily(SimpleNamespace(data_dir=root), library, path=local).macros())
            self.assertIn("pet_guild", (root / "daily.json").read_text())

    def test_pet_upgrade_preserves_removed_macros_and_can_be_removed_afterward(self):
        from league_bot.slayer.selection import open_home_daily
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = root / "home.json"
            local.write_text('{"macros":["custom"],"last_run":"yesterday"}')
            library = SimpleNamespace(find=lambda name: True)
            entries = open_home_daily(SimpleNamespace(data_dir=root),library,path=local)
            self.assertEqual(entries.macros(),["custom","pet_guild"])
            self.assertIn("yesterday",local.read_text())
            entries.remove("pet_guild")
            self.assertEqual(open_home_daily(SimpleNamespace(data_dir=root),library,path=local).macros(),["custom"])

    def test_known_recording_preserves_guards_between_home_recovery(self):
        from unittest.mock import patch
        settings = la.load_settings(environ={}, env_file=None)
        game = la.HomeSlayerGame(settings, object())
        raw = [{"action": "wait_for_pixel", "x": 3, "y": 5, "color": [1, 2, 3]},
               {"action": "click", "x": 3, "y": 5}]
        with patch.object(la.SlayerGame, "load_macro_steps", return_value=raw):
            steps = game.load_macro_steps("blorb")
        self.assertEqual(steps[3]["terminal"], "main")
        self.assertEqual(steps[4:6], raw)
        self.assertEqual(steps[6]["terminal"], "main")
        self.assertEqual(steps[-1]["action"], "minimize")
        self.assertEqual(len(raw), 2)

    def test_failure_preserves_last_success_for_cooldown_and_rollover_removes_it(self):
        with tempfile.TemporaryDirectory() as folder:
            now = [datetime(2026, 10, 11, 12, tzinfo=ZoneInfo("America/Sao_Paulo"))]
            store = DailyStatusStore(Path(folder) / "status.json", now=lambda: now[0])
            store.mark_progress("macro:blorb", 1, 3, source="macro")
            completed = store.snapshot()["tasks"]["macro:blorb"]["last_completed_at"]
            now[0] += timedelta(minutes=2)
            store.mark_error("macro:blorb", "failed")
            snapshot = store.snapshot()
            self.assertEqual(snapshot["tasks"]["macro:blorb"]["last_completed_at"], completed)
            self.assertEqual(snapshot["tasks"]["macro:blorb"]["last_completed_at"], completed)
            now[0] += timedelta(days=1)
            self.assertNotIn("last_completed_at", store.snapshot()["tasks"]["macro:blorb"])


if __name__ == "__main__":
    unittest.main()
