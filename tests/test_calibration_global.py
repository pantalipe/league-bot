import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from league_bot.imaging import solid_frame
from league_bot.slayer.calibration_global import (
    GlobalCalibrationError, add, apply, create_session, coverage, propose, rollback, transform, validate, write_report,
)
from league_bot.slayer.calibration_inventory import screen_signature, step_signature


def _inventory():
    anchors = [{"x": 0.1, "y": 0.1, "color": [100, 100, 100], "tolerance": 10, "radius": 0},
               {"x": 0.2, "y": 0.2, "color": [100, 100, 100], "tolerance": 10, "radius": 0}]
    screen = {"name": "fixture", "anchors": anchors, "click": {"x": 12, "y": 34}}
    pixel = {"action": "wait_for_pixel", "x": "50%", "y": 200, "color": [100, 100, 100], "radius": 0,
             "tolerance": 10, "timeout": 1}
    entries = {
        "screen:fixture": {"id": "screen:fixture", "kind": "screen", "source": "macros/demo.json",
                           "pointer": "/steps/0/screens/0/anchors", "base": screen,
                           "signature": screen_signature(anchors), "reference_size": [434, 810], "name": "fixture"},
        "pixel:fixture": {"id": "pixel:fixture", "kind": "pixel", "source": "macros/demo.json",
                          "pointer": "/steps/1", "base": pixel, "signature": step_signature(pixel),
                          "reference_size": [434, 810], "name": "fixture pixel"},
        "click:fixture": {"id": "click:fixture", "kind": "click", "source": "macros/demo.json",
                          "pointer": "/steps/2", "base": {"action": "click", "x": 20, "y": 30},
                          "signature": "clicksig", "reference_size": [434, 810], "name": "fixed click"},
    }
    return {"version": 2, "reference_size": [434, 810], "entries": entries, "macros": {}, "errors": []}


class GlobalCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inv = _inventory()
        self.session = self.root / "session"
        self.session.mkdir()
        self.samples = self.root / "input"
        self.samples.mkdir()
        for label, color, i in (("positive", (130, 130, 130), 1), ("positive", (130, 130, 130), 2),
                                ("negative", (100, 100, 100), 3)):
            (self.samples / f"{i}.png").write_bytes(solid_frame(434, 810, color).to_png())
        create_session(self.session, self.inv)

    def tearDown(self):
        self.tmp.cleanup()

    def _label_all(self, ident):
        for label, filename in (("positive", "1.png"), ("positive", "2.png"), ("negative", "3.png")):
            add(self.session, ident, label, self.samples / filename, self.inv)

    def test_coverage_reports_unobserved_entries_pending(self):
        result = coverage(self.session, self.inv)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["ready"], 0)

    def test_pixel_and_screen_proposal_validation_runtime_transform_and_rollback(self):
        self._label_all("screen:fixture")
        self._label_all("pixel:fixture")
        candidate_path = propose(self.session, self.inv)
        report_path = self.session / "report.html"
        self.assertTrue(report_path.exists())
        self.assertIn("Ações de clique", report_path.read_text(encoding="utf-8"))
        self.assertIn("href=\"samples/", report_path.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        self.assertEqual(set(candidate["profiles"]), {"screen:fixture", "pixel:fixture"})
        self.assertTrue(validate(self.session, self.inv)["ok"])
        active = apply(self.session, self.root / "data", self.inv)

        screen_step = {"action": "screen_flow", "terminal": "done", "screens": [
            {"name": "fixture", "anchors": self.inv["entries"]["screen:fixture"]["base"]["anchors"],
             "click": {"x": 12, "y": 34}},
            {"name": "done", "anchors": [{"x": .8, "y": .8, "color": [0, 0, 0]},
                                             {"x": .9, "y": .9, "color": [0, 0, 0]}]}]}
        updated_screen = transform(screen_step, self.root / "data", "macros/demo.json")
        self.assertEqual(updated_screen["screens"][0]["anchors"][0]["color"], [130, 130, 130])
        self.assertEqual(updated_screen["screens"][0]["click"], {"x": 12, "y": 34})
        original_pixel = self.inv["entries"]["pixel:fixture"]["base"]
        updated_pixel = transform(original_pixel, self.root / "data", "macros/demo.json")
        self.assertEqual(updated_pixel["color"], [130, 130, 130])
        self.assertEqual((updated_pixel["x"], updated_pixel["y"]), (original_pixel["x"], original_pixel["y"]))
        self.assertTrue(active.exists())
        rollback(self.root / "data")
        self.assertFalse(active.exists())

    def test_incomplete_evidence_is_not_calibrated(self):
        add(self.session, "pixel:fixture", "positive", self.samples / "1.png", self.inv)
        add(self.session, "pixel:fixture", "negative", self.samples / "3.png", self.inv)
        path = propose(self.session, self.inv)
        candidate = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("pixel:fixture", candidate["profiles"])
        result = validate(self.session, self.inv)
        self.assertFalse(result["ok"])
        self.assertTrue(any("two positive" in error for error in result["errors"]))
        self.assertEqual(result["profiles"], 0)

    def test_source_baseline_change_invalidates_session(self):
        changed = _inventory()
        changed["entries"]["screen:fixture"]["base"]["click"]["x"] += 1
        with self.assertRaises(GlobalCalibrationError):
            coverage(self.session, changed)

    def test_add_and_coverage_bootstrap_a_fresh_session(self):
        fresh = self.root / "fresh"
        add(fresh, "pixel:fixture", "positive", self.samples / "1.png", self.inv)
        result = coverage(fresh, self.inv)
        self.assertEqual(result["entries"]["pixel:fixture"]["positive"], 1)
        self.assertTrue((fresh / "session.json").exists())

    def test_baseline_that_also_matches_negative_is_rejected(self):
        same = self.root / "same.png"
        same.write_bytes(solid_frame(434, 810, (100, 100, 100)).to_png())
        for ident in ("screen:fixture", "pixel:fixture"):
            add(self.session, ident, "positive", [same, same], self.inv)
            add(self.session, ident, "negative", same, self.inv)
        propose(self.session, self.inv)
        report = validate(self.session, self.inv)
        self.assertFalse(report["ok"])
        self.assertTrue(any("negative" in error.lower() or "matches" in error.lower()
                            for error in report["errors"]))

    def test_validate_rejects_missing_profile_for_evidence_ready_entry(self):
        self._label_all("pixel:fixture")
        path = propose(self.session, self.inv)
        candidate = json.loads(path.read_text(encoding="utf-8"))
        candidate["profiles"].pop("pixel:fixture", None)
        path.write_text(json.dumps(candidate), encoding="utf-8")
        report = validate(self.session, self.inv)
        self.assertFalse(report["ok"])
        self.assertTrue(any("missing from candidate" in error for error in report["errors"]))

    def test_standalone_asset_anchor_list_can_be_validated_and_applied(self):
        inv = _inventory()
        original = inv["entries"].pop("screen:fixture")
        original["id"] = "screen:standalone"
        original["source"] = "slayer/assets/navigation.json"
        original["pointer"] = "/main_closed_anchors"
        original["base"] = original["base"]["anchors"]
        inv["entries"][original["id"]] = original
        inv["entries"].pop("pixel:fixture")
        inv["entries"].pop("click:fixture")
        session = self.root / "standalone"
        create_session(session, inv)
        for label, filename in (("positive", "1.png"), ("positive", "2.png"), ("negative", "3.png")):
            add(session, "screen:standalone", label, self.samples / filename, inv)
        propose(session, inv)
        self.assertTrue(validate(session, inv)["ok"])
        data_dir = self.root / "standalone_data"
        apply(session, data_dir, inv)
        step = {"action": "screen_flow", "screens": [{"name": "fixture", "anchors": original["base"]}]}
        transformed = transform(step, data_dir, "slayer/assets/navigation.json")
        self.assertEqual(transformed["screens"][0]["anchors"][0]["color"], [130, 130, 130])

    def test_report_escapes_untrusted_names_and_sources(self):
        inv = _inventory()
        inv["entries"]["screen:fixture"]["name"] = '<script>alert("x")</script>'
        inv["entries"]["screen:fixture"]["source"] = 'macros/<img src=x onerror="bad">.json'
        session = self.root / "escaped"
        create_session(session, inv)
        report = write_report(session, inv).read_text(encoding="utf-8")
        self.assertNotIn('<script>alert', report)
        self.assertNotIn('<img src=x', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('&lt;img src=x', report)

    def test_propose_reuses_only_exact_profile_evidence_and_source(self):
        self._label_all("screen:fixture")
        from league_bot.slayer import calibration as v1
        with patch("league_bot.slayer.calibration_global.v1.propose", wraps=v1.propose) as propose_screen:
            propose(self.session, self.inv)
            self.assertEqual(propose_screen.call_count, 1)
            propose(self.session, self.inv)
            self.assertEqual(propose_screen.call_count, 1)

            manifest_path = self.session / "session.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            records = manifest["entries"]["screen:fixture"]["samples"]
            records[0]["label"] = "negative"
            records[-1]["label"] = "positive"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            propose(self.session, self.inv)
            self.assertEqual(propose_screen.call_count, 2)

    def test_new_inventory_entry_does_not_invalidate_other_cached_profiles(self):
        self._label_all("screen:fixture")
        propose(self.session, self.inv)
        expanded = copy.deepcopy(self.inv)
        click = {"action": "click", "x": 1, "y": 2}
        expanded["entries"]["click:new"] = {
            "id": "click:new", "kind": "click", "source": "macros/new.json", "pointer": "/0",
            "base": click, "signature": "new-click", "reference_size": [434, 810], "name": "new click"}
        old_manifest = json.loads((self.session / "session.json").read_text(encoding="utf-8"))
        create_session(self.session, expanded)
        migrated = json.loads((self.session / "session.json").read_text(encoding="utf-8"))
        migrated["entries"]["screen:fixture"]["samples"] = old_manifest["entries"]["screen:fixture"]["samples"]
        (self.session / "session.json").write_text(json.dumps(migrated), encoding="utf-8")

        from league_bot.slayer import calibration as v1
        with patch("league_bot.slayer.calibration_global.v1.propose", wraps=v1.propose) as propose_screen:
            propose(self.session, expanded)
            self.assertEqual(propose_screen.call_count, 0)
        self.assertTrue(validate(self.session, expanded)["ok"])

    def test_transform_rejects_malformed_active_data_and_changed_pixel_coordinates(self):
        data_dir = self.root / "bad_data"
        active = data_dir / "calibration" / "global-active.json"
        active.parent.mkdir(parents=True)
        active.write_text(json.dumps({"version": 1, "profiles": []}), encoding="utf-8")
        with self.assertRaises(GlobalCalibrationError):
            transform(self.inv["entries"]["pixel:fixture"]["base"], data_dir)

        self._label_all("pixel:fixture")
        propose(self.session, self.inv)
        apply(self.session, data_dir, self.inv)
        contents = json.loads(active.read_text(encoding="utf-8"))
        profile = contents["profiles"]["pixel:fixture"]
        profile["value"]["x"] = 9
        active.write_text(json.dumps(contents), encoding="utf-8")
        with self.assertRaises(GlobalCalibrationError):
            transform(self.inv["entries"]["pixel:fixture"]["base"], data_dir)


if __name__ == "__main__":
    unittest.main()
