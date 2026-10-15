import copy
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from league_bot.imaging import Frame, solid_frame
from league_bot.slayer import calibration as cal


def screen(name="probe", color=(200, 20, 20)):
    return {"name": name, "anchors": [{"x": .5, "y": .5, "color": list(color), "tolerance": 10,
                                         "radius": 0},
                                        {"x": 0, "y": 0, "color": list(color), "tolerance": 10,
                                         "radius": 0}], "click": {"x": 12, "y": 34}}


def stripe_frame(color, *, width=30, height=30, stripe_x=15):
    stride = ((width * 3 + 3) // 4) * 4
    data = bytearray(stride * height)
    for y in range(height):
        for x in range(width):
            rgb = color if x == stripe_x else (0, 0, 0)
            off = (height - 1 - y) * stride + x * 3
            data[off:off + 3] = bytes((rgb[2], rgb[1], rgb[0]))
    return Frame(width, height, bytes(data))


def with_pixel(frame, x, y, rgb):
    data = bytearray(frame.bgr)
    offset = (frame.height - 1 - y) * frame.row_size + x * 3
    data[offset:offset + 3] = bytes((rgb[2], rgb[1], rgb[0]))
    return Frame(frame.width, frame.height, bytes(data))


class SlayerCalibrationTests(unittest.TestCase):
    def test_empty_session_cannot_activate_only_bundled_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "session.json").write_text('{"version": 1, "samples": []}', encoding="utf-8")
            with self.assertRaisesRegex(cal.CalibrationError, "sem capturas do usuario"):
                cal.build_candidate(tmp)
            self.assertFalse(Path(tmp, "candidate.json").exists())

    def test_diagnose_reports_channel_deltas_and_match(self):
        report = cal.diagnose(solid_frame(20, 20, (202, 18, 20)), screen())
        self.assertEqual(report["anchors"][0]["delta"], [2, 2, 0])
        self.assertTrue(report["matched"])

    def test_propose_moves_to_stable_nearby_sample_without_widening_or_changing_click(self):
        original = screen(color=(200, 20, 20))
        original["anchors"][1]["color"] = [0, 0, 0]
        positives = [stripe_frame((204, 22, 21)), stripe_frame((202, 19, 20))]
        negative = stripe_frame((0, 0, 0))
        result = cal.propose(original, positives, [negative], search_radius=8)
        self.assertNotEqual(result["anchors"][0]["x"], original["anchors"][0]["x"])
        self.assertEqual(result["anchors"][0]["tolerance"], 10)
        self.assertEqual(result["click"], original["click"])
        self.assertEqual(original["anchors"][0]["x"], .5)

    def test_propose_requires_two_positives_and_a_negative_and_rejects_unstable(self):
        f = stripe_frame((202, 20, 20))
        with self.assertRaises(cal.CalibrationError):
            cal.propose(screen(), [f], [f])
        # No nearby point is consistently the anchor color across these frames.
        first, second = stripe_frame((255, 0, 0)), stripe_frame((0, 255, 0))
        unstable = screen()
        unstable["anchors"][1]["color"] = [0, 0, 0]
        with self.assertRaises(cal.CalibrationError):
            cal.propose(unstable, [first, second], [stripe_frame((0, 0, 0))], search_radius=0)

    def test_validation_rejects_tampered_click_tolerance_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = {"version": 1, "frame_size": list(cal.SIZE), "base": cal.catalog(),
                         "profiles": cal.catalog(), "evidence": []}
            for mutation in ("click", "tolerance", "evidence"):
                changed = copy.deepcopy(candidate)
                if mutation == "click":
                    changed["profiles"]["menu_open"]["click"]["x"] += 1
                elif mutation == "tolerance":
                    changed["profiles"]["menu_open"]["anchors"][0]["tolerance"] += 1
                else:
                    changed["evidence"].append({"image": "fake.png", "sha256": "0", "states": []})
                Path(tmp, "candidate.json").write_text(json.dumps(changed), encoding="utf-8")
                report = cal.validate_candidate(tmp)
                self.assertFalse(report["ok"], mutation)

    def test_capture_and_build_candidate_include_all_historical_references(self):
        if importlib.util.find_spec("PIL") is None:
            self.skipTest("fixture PNG decoding requires the optional Pillow calibration extra")
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp, "session")
            fixtures = Path("tests/fixtures/slayer")
            pairs = [("menu_open", "menu-open.png"), ("menu_open", "menu-open-current.png"),
                     ("settings_open", "settings.png"), ("settings_open", "settings-current.png"),
                     ("attendance_claim_ready", "attendance-ready.png"),
                     ("attendance_claim_ready", "attendance-ready-current.png"),
                     ("attendance_claimed", "attendance-claimed.png"),
                     ("attendance_claimed_settings", "attendance-settings.png")]
            for state, name in pairs:
                cal.add_sample(session, state, [fixtures / name])
            cal.capture_sample(session, "unknown", [solid_frame(*cal.SIZE, (0, 0, 0))])
            cal.build_candidate(session)
            data = json.loads(Path(session, "candidate.json").read_text(encoding="utf-8"))
            reference_count = len(json.loads((cal.ASSETS / "calibration-samples" / "samples.json").read_text()))
            self.assertEqual(len(data["evidence"]), len(pairs) + 1 + reference_count)
            self.assertTrue(cal.validate_candidate(session)["ok"])

    def test_real_fixture_evidence_validates_activates_and_overrides_menu_return_alias(self):
        if importlib.util.find_spec("PIL") is None:
            self.skipTest("fixture PNG decoding requires the optional Pillow calibration extra")
        from league_bot.slayer.home import home_step

        with tempfile.TemporaryDirectory() as tmp:
            session, data = Path(tmp, "session"), Path(tmp, "data")
            fixture_dir = Path("tests/fixtures/slayer")
            base = cal.catalog()
            anchor = base["menu_open"]["anchors"][0]
            x, y = round(anchor["x"] * (cal.SIZE[0] - 1)), round(anchor["y"] * (cal.SIZE[1] - 1))
            for name in ("menu-open.png", "menu-open-current.png"):
                frame = cal.load_image(fixture_dir / name)
                # Simulate a small overlay at the old sample. The adjacent original
                # feature remains stable in both captures and historical references.
                cal.capture_sample(session, "menu_open", [with_pixel(frame, x, y, (0, 0, 0))])
            cal.build_candidate(session)
            candidate = json.loads(Path(session, "candidate.json").read_text(encoding="utf-8"))
            self.assertNotEqual(candidate["profiles"]["menu_open"]["anchors"],
                                candidate["base"]["menu_open"]["anchors"])
            self.assertTrue(cal.validate_candidate(session)["ok"])
            active = cal.apply_candidate(session, data)
            recovery = home_step()
            before = next(s for s in recovery["screens"] if s["name"] == "menu_return")
            after = next(s for s in cal.apply_overrides([recovery], data)[0]["screens"]
                         if s["name"] == "menu_return")
            self.assertEqual(before["click"], after["click"])
            self.assertEqual(after["anchors"], candidate["profiles"]["menu_open"]["anchors"])
            self.assertEqual(len(candidate["evidence"]), 2 + len(json.loads(
                (cal.ASSETS / "calibration-samples" / "samples.json").read_text(encoding="utf-8"))))
            self.assertTrue(active.exists())

    def test_unknown_sample_matching_another_catalog_screen_is_rejected(self):
        if importlib.util.find_spec("PIL") is None:
            self.skipTest("fixture PNG decoding requires the optional Pillow calibration extra")
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp, "session")
            cal.capture_sample(session, "unknown", [cal.load_image(Path("tests/fixtures/slayer/settings.png"))])
            with self.assertRaisesRegex(cal.CalibrationError, "settings_open"):
                cal.build_candidate(session)
            report = cal.validate_candidate(session)
            self.assertFalse(report["ok"])
            self.assertTrue(any("settings_open" in error or "settings_return" in error
                                for error in report["errors"]))

    def test_activation_overrides_preserve_clicks_and_rollback_first_or_previous(self):
        profiles = cal.catalog()
        base = cal.catalog()
        # Shift one anchor to a legal coordinate; leave all click metadata untouched.
        profiles["menu_open"]["anchors"][0]["x"] = min(.99, profiles["menu_open"]["anchors"][0]["x"] + .001)
        candidate = {"version": 1, "frame_size": list(cal.SIZE), "base": base,
                     "profiles": profiles, "evidence": []}
        original_steps = [{"action": "screen_flow", "frame_size": list(cal.SIZE), "screens": [
            copy.deepcopy(base["menu_open"])]}, {"action": "click", "x": 7, "y": 8}]
        with tempfile.TemporaryDirectory() as tmp:
            session, data = Path(tmp, "session"), Path(tmp, "data")
            session.mkdir()
            Path(session, "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
            with mock.patch.object(cal, "validate_candidate", return_value={"ok": True, "errors": []}):
                cal.apply_candidate(session, data)
            active = data / "calibration" / "active.json"
            self.assertTrue(active.exists())
            applied = cal.apply_overrides(original_steps, data)
            self.assertEqual(original_steps[0]["screens"][0]["click"], applied[0]["screens"][0]["click"])
            self.assertEqual(original_steps[1], applied[1])
            self.assertNotEqual(original_steps[0]["screens"][0]["anchors"],
                                applied[0]["screens"][0]["anchors"])
            cal.rollback(data)
            # The first activation had no prior profile, so rollback removes it.
            self.assertFalse(active.exists())
            # Activating again then rolling back restores the immediately previous profile.
            with mock.patch.object(cal, "validate_candidate", return_value={"ok": True, "errors": []}):
                cal.apply_candidate(session, data)
            before = json.loads(active.read_text(encoding="utf-8"))
            with mock.patch.object(cal, "validate_candidate", return_value={"ok": True, "errors": []}):
                cal.apply_candidate(session, data)
            cal.rollback(data)
            self.assertEqual(json.loads(active.read_text(encoding="utf-8")), before)

    def test_frame_size_and_stale_baseline_guards(self):
        old = cal.catalog()
        with tempfile.TemporaryDirectory() as tmp:
            candidate = {"version": 1, "frame_size": [1, 2], "base": old, "profiles": old, "evidence": []}
            Path(tmp, "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
            self.assertFalse(cal.validate_candidate(tmp)["ok"])
            candidate["frame_size"] = list(cal.SIZE)
            candidate["base"]["main"]["anchors"][0]["color"][0] ^= 1
            Path(tmp, "candidate.json").write_text(json.dumps(candidate), encoding="utf-8")
            self.assertFalse(cal.validate_candidate(tmp)["ok"])

    def test_malformed_active_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp, "calibration", "active.json")
            active.parent.mkdir()
            active.write_text('{"version": 1, "frame_size": [1, 2]}', encoding="utf-8")
            with self.assertRaises(cal.CalibrationError):
                cal.apply_overrides([], tmp)


if __name__ == "__main__":
    unittest.main()
