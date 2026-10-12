"""Catalog and validation coverage for the newly shipped one-time pickups."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests import slayer_compat as la

if la.available():
    from league_bot.daily import DailyList
    from league_bot.macro import validate_steps
    from league_bot.slayer.plan import DEFAULT_MACROS, FINISHED_DAILIES, MACRO_CATALOG, REPEATED_MACROS, ordered_macros


MACRO_DIR = ROOT / "league_bot" / "slayer" / "macros"
NEW_MACROS = ("collect_familiar", "mailbox")


class FakeLibrary:
    def __init__(self, names):
        self.names_ = set(names)

    def find(self, name):
        return name if name in self.names_ else None


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class NewDailyCollectionTests(unittest.TestCase):
    def test_catalog_defaults_and_order_include_both_once_before_final_collection(self):
        self.assertTrue(set(NEW_MACROS).issubset(MACRO_CATALOG))
        self.assertTrue(set(NEW_MACROS).issubset(DEFAULT_MACROS))
        self.assertEqual(len(DEFAULT_MACROS), 20)
        self.assertTrue(all(name not in REPEATED_MACROS for name in NEW_MACROS))
        ordered = ordered_macros(DEFAULT_MACROS)
        for name in NEW_MACROS:
            self.assertEqual(ordered.count(name), 1)
            self.assertLess(ordered.index(name), ordered.index(FINISHED_DAILIES))
        self.assertEqual(ordered[-1], FINISHED_DAILIES)

    def test_selected_custom_macros_remain_selected_and_new_names_can_be_added(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.json"
            path.write_text(json.dumps({"macros": ["custom_macro"]}), encoding="utf-8")
            daily = DailyList(path, FakeLibrary({"custom_macro", *NEW_MACROS}))
            daily.add("collect_familiar")
            daily.add("mailbox")
            self.assertEqual(daily.macros(), ["custom_macro", *NEW_MACROS])
            # The list is persisted as the selected plan; catalog defaults do
            # not overwrite an existing user's selection.
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["macros"],
                             ["custom_macro", *NEW_MACROS])

    def test_shipped_recordings_validate_and_are_single_run_claim_flows(self):
        expected_clicks = {"collect_familiar": 7, "mailbox": 8}
        for name, count in expected_clicks.items():
            data = json.loads((MACRO_DIR / f"{name}.json").read_text(encoding="utf-8"))
            with self.subTest(name=name):
                validate_steps(data["steps"])
                self.assertEqual(data["window"], {"width": 434, "height": 810})
                self.assertEqual(data["steps"][0]["action"], "wait_window")
                self.assertEqual(sum(step["action"] == "click" for step in data["steps"]), count)
                self.assertTrue(all(step["action"] in {"wait_window", "wait_for_pixel", "click", "wait"}
                                    for step in data["steps"]))
                self.assertNotIn(name, REPEATED_MACROS)  # one collection per daily run


if __name__ == "__main__":
    unittest.main()
