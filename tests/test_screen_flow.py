import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from league_bot.macro import MacroCancelled, MacroError, MacroRunner, load_macro, validate_steps
from tests.fakes import FakeBackend, FakeTime


def state(name, color, click=False):
    result = {"name": name, "anchors": [
        {"x": 0.2, "y": 0.2, "color": [color] * 3, "tolerance": 0},
        {"x": 0.8, "y": 0.8, "color": [color] * 3, "tolerance": 0},
    ]}
    if click:
        result["click"] = {"x": "center", "y": "center"}
    return result


def flow(**overrides):
    result = {"action": "screen_flow", "terminal": "main", "timeout": 6,
              "poll_seconds": 0.5, "stable_frames": 2,
              "screens": [state("tap", 100, True), state("save", 150, True), state("main", 200)]}
    result.update(overrides)
    return result


class ScreenFlowTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend(size=(10, 10))
        self.time = FakeTime()
        self.runner = MacroRunner(self.backend, "Slayer Legend", foreground=True,
                                  sleep=self.time.sleep, clock=self.time.clock)

    def test_save_is_confirmed_and_terminal_verified_without_real_input(self):
        self.backend.frames = [(v, v, v) for v in (100, 100, 100, 100, 150, 150, 200, 200)]
        self.runner.run([flow(), {"action": "minimize"}])
        self.assertEqual(self.backend.clicks(), [(5, 5, False), (5, 5, False)])
        self.assertTrue(self.backend.minimized)

    def test_save_can_be_absent_and_loading_frames_are_not_clicked(self):
        self.backend.frames = [(v, v, v) for v in (0, 100, 100, 0, 0, 200, 200)]
        self.runner.run([flow()])
        self.assertEqual(self.backend.clicks(), [(5, 5, False)])

    def test_persistent_screen_is_not_reclicked_and_saves_evidence(self):
        self.backend.fill = (100, 100, 100)
        with tempfile.TemporaryDirectory() as tmp:
            self.runner.diagnostics_dir = Path(tmp)
            with self.assertRaisesRegex(MacroError, "timed out.*screenshot"):
                self.runner.run([flow(timeout=2), {"action": "minimize"}])
            files = list(Path(tmp).glob("*.png"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].read_bytes().startswith(b"\x89PNG"))
        self.assertEqual(self.backend.clicks(), [(5, 5, False)])
        self.assertFalse(self.backend.minimized)

    def test_transient_terminal_does_not_finish_flow(self):
        self.backend.frames = [(v, v, v) for v in (200, 0, 0)]
        with self.assertRaisesRegex(MacroError, "timed out"):
            self.runner.run([flow(timeout=2)])
        self.assertEqual(self.backend.clicks(), [])

    def test_ambiguous_frame_fails_without_clicking(self):
        step = flow()
        step["screens"][1]["anchors"] = copy.deepcopy(step["screens"][0]["anchors"])
        self.backend.fill = (100, 100, 100)
        with self.assertRaisesRegex(MacroError, "ambiguous"):
            self.runner.run([step])
        self.assertEqual(self.backend.clicks(), [])

    def test_returned_screen_has_a_bounded_click_budget(self):
        self.backend.frames = [(v, v, v) for v in (100, 100, 150, 150, 100, 100)]
        with self.assertRaisesRegex(MacroError, "click limit"):
            self.runner.run([flow()])
        self.assertEqual(len(self.backend.clicks()), 2)

    def test_cancel_stops_waiting_without_a_click(self):
        self.runner._sleep = lambda seconds: self.runner.cancel()
        with self.assertRaises(MacroCancelled):
            self.runner.run([flow()])
        self.assertEqual(self.backend.clicks(), [])

    def test_uncalibrated_and_invalid_configuration_fails_before_window_access(self):
        for key, bad in (("timeout", 0), ("timeout", float("nan")), ("poll_seconds", -1),
                         ("stable_frames", True), ("stable_frames", 1),
                         ("frame_size", [434, False]), ("frame_size", [0, 810]),
                         ("frame_size", "434x810"), ("frame_size", None)):
            with self.subTest(key=key, value=bad), self.assertRaises(MacroError):
                self.runner.run([flow(**{key: bad})])
        step = flow()
        step["screens"][0]["anchors"] = []
        with self.assertRaises(MacroError):
            self.runner.run([step])
        self.assertEqual(self.backend.calls, [])

    def test_background_backend_failure_is_reported_as_macro_failure(self):
        self.backend.fill = (100, 100, 100)
        def fail(*args):
            raise OSError("emulator surface not found")
        self.backend.click = fail
        with self.assertRaisesRegex(MacroError, "surface not found"):
            self.runner.run([flow()])

    def test_slow_capture_does_not_click_after_deadline(self):
        capture = self.backend.capture
        def slow_capture(hwnd):
            frame = capture(hwnd)
            self.time.now += 3
            return frame
        self.backend.fill = (100, 100, 100)
        self.backend.capture = slow_capture
        with self.assertRaisesRegex(MacroError, "timed out"):
            self.runner.run([flow(timeout=2)])
        self.assertEqual(self.backend.clicks(), [])

    def test_missing_capture_has_no_click_or_diagnostic(self):
        self.backend.capture = lambda hwnd: None
        with tempfile.TemporaryDirectory() as tmp:
            self.runner.diagnostics_dir = Path(tmp)
            with self.assertRaisesRegex(MacroError, "timed out"):
                self.runner.run([flow(timeout=1)])
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(self.backend.clicks(), [])

    def test_diagnostic_write_failure_preserves_original_error(self):
        self.backend.fill = (100, 100, 100)
        self.runner.diagnostics_dir = Path("unused")
        with patch.object(Path, "mkdir", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(MacroError, "timed out"):
                self.runner.run([flow(timeout=2)])

    def test_prepare_always_places_window_in_background(self):
        self.backend.minimized = True
        self.runner.run([{"action": "prepare_window"}, {"action": "prepare_window"}])
        self.assertEqual(self.backend.calls.count(("restore",)), 2)

    def test_pixel_wait_restores_minimized_window_before_capture(self):
        self.backend.minimized = True
        self.runner.run([{"action": "wait_for_pixel", "x": 1, "y": 1, "color": [10, 10, 10]}])
        self.assertEqual(self.backend.calls[:2], [("restore",), ("capture",)])

    def test_click_coordinates_are_measured_after_restore(self):
        self.backend.minimized = True
        original_size = self.backend.client_size
        self.backend.client_size = lambda hwnd: (156, 24) if self.backend.minimized else original_size(hwnd)
        self.runner.run([{"action": "click", "x": "center", "y": "center"}])
        self.assertEqual(self.backend.clicks(), [(5, 5, True)])
        self.assertEqual(self.backend.calls[0], ("restore",))

    def test_profile_template_is_rejected_until_calibrated(self):
        path = Path(__file__).resolve().parent.parent / "docs" / "start-game-recognized.template.json"
        with self.assertRaisesRegex(MacroError, "at least two anchors"):
            load_macro(path)

    def test_invalid_clicks_fail_early_or_are_bounded_at_runtime(self):
        for coords in ({"x": "100%", "y": "center"}, {"x": -1, "y": "center"},
                       {"x": float("inf"), "y": "center"}):
            step = flow()
            step["screens"][0]["click"] = coords
            with self.assertRaises(MacroError):
                validate_steps([step])
        step = flow()
        step["screens"][0]["click"] = {"x": 99, "y": 99}
        self.backend.fill = (100, 100, 100)
        with self.assertRaisesRegex(MacroError, "outside"):
            self.runner.run([step])
        self.assertEqual(self.backend.clicks(), [])


if __name__ == "__main__":
    unittest.main()
