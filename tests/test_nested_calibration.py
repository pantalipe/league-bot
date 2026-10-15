"""Specialized runners must calibrate flows constructed after a macro starts."""
import copy
import tempfile
import unittest
from pathlib import Path

from league_bot.config import load_settings
from league_bot.imaging import solid_frame
from league_bot.macro import MacroRunner
from league_bot.slayer.game import SlayerDailyGame
from tests.test_slayer_attendance import FakeBackend, FakeTime


class NestedCalibrationTests(unittest.TestCase):
    def test_specialized_runner_uses_host_transform_on_dynamic_flow(self):
        step = dict(action="screen_flow", terminal="main", nested=True,
                    frame_size=[434,810], timeout=1, poll_seconds=.2, stable_frames=2,
                    screens=[dict(name="main", anchors=[
                        dict(x=.1,y=.1,color=[9,9,9],tolerance=0),
                        dict(x=.9,y=.9,color=[9,9,9],tolerance=0)])])
        transformed = []
        class NestedRunner(MacroRunner):
            def _do_screen_flow(self, outer, hwnd):
                dynamic = copy.deepcopy(outer)
                dynamic.pop("nested")
                return super()._do_screen_flow(dynamic, hwnd)
        class CalibratedGame(SlayerDailyGame):
            def _calibrate_screen(self, current):
                transformed.append(copy.deepcopy(current))
                current = copy.deepcopy(current)
                for anchor in current["screens"][0]["anchors"]:
                    anchor["color"] = [1,2,3]
                return current
        clock = FakeTime()
        backend = FakeBackend([solid_frame(434,810,(1,2,3))]*2)
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings(environ={"SLAYER_DATA_DIR":tmp},env_file=None)
            game = CalibratedGame(settings,backend,runner_factory=lambda b,t,f,l:
                NestedRunner(b,t,f,l,sleep=clock.sleep,clock=clock.clock))
            game._run_steps([step],"nested","Slayer Legend")
        self.assertGreaterEqual(len(transformed),1)
        self.assertTrue(any("nested" not in step for step in transformed))
        self.assertEqual(step["screens"][0]["anchors"][0]["color"],[9,9,9])
        self.assertEqual(backend.click_log,[])
