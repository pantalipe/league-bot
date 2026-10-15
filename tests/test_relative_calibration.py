import math
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

from league_bot.imaging import solid_frame
from league_bot.macro import MacroError, MacroRunner, resolve_coord
from league_bot.screens import calibrated_matching, matching_screens
from tests.test_slayer_attendance import FakeBackend, FakeTime


class RelativeCalibrationTests(unittest.TestCase):
    def test_geometry_command_repairs_invalid_profile_without_loading_game(self):
        from league_bot.__main__ import build_parser
        from league_bot.calibration_global_cli import run
        from league_bot.config import Settings
        import json
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            profile = data / "calibration/geometry.json"
            profile.parent.mkdir()
            profile.write_text("invalid json")
            raw = SimpleNamespace(find_window=lambda title:1,client_size=lambda hwnd:(434,810),
                                  viewport=lambda hwnd:(0,36,434,774))
            factory = Mock(side_effect=AssertionError("must not load broken game profile"))
            args = build_parser().parse_args(["calibrate","all","geometry"])
            with patch("league_bot.winapi.Win32Backend",return_value=raw):
                self.assertEqual(run(args,Settings(data_dir=data,window_title="Slayer Legend"),factory),0)
            self.assertEqual(json.loads(profile.read_text())["reference_viewport"],[0,36,434,774])
            factory.assert_not_called()

    def test_relative_coordinates_preserve_reference_pixels_and_scale(self):
        for x in (0, 1, 217, 409, 433):
            self.assertEqual(resolve_coord({"relative": x / 433}, 434), x)
        self.assertEqual(resolve_coord({"relative": .5}, 867), 433)
        for invalid in (True, -1, 1.1, math.nan, math.inf, "50%"):
            with self.assertRaises(MacroError):
                resolve_coord({"relative": invalid}, 434)

    def test_direct_classifier_calibration_is_scoped(self):
        screen = dict(name="known", anchors=[dict(x=.1,y=.1,color=[1,2,3]),
                                             dict(x=.9,y=.9,color=[1,2,3])])
        frame = solid_frame(10,10,(90,90,90))
        def transform(screens):
            return [dict(s, anchors=[dict(a,color=[90,90,90]) for a in s["anchors"]]) for s in screens]
        with calibrated_matching(transform):
            self.assertEqual(matching_screens(frame,[screen]),["known"])
        self.assertEqual(matching_screens(frame,[screen]),[])
        self.assertEqual(screen["anchors"][0]["color"],[1,2,3])

    def test_dynamic_pixel_transform_and_fresh_failure_frame(self):
        frame = solid_frame(434,810,(90,90,90))
        clock = FakeTime()
        runner = MacroRunner(FakeBackend([frame]*4),"Slayer Legend",False,
                             sleep=clock.sleep,clock=clock.clock)
        runner.step_transform = lambda step: dict(step,color=[90,90,90])
        step = dict(action="wait_for_pixel",x={"relative":.5},y={"relative":.5},
                    color=[1,2,3],timeout=.5)
        runner.run([step])
        self.assertIs(runner._last_frame,frame)
        self.assertEqual(step["color"],[1,2,3])


if __name__ == "__main__":
    unittest.main()
