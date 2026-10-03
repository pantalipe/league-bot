import json
import unittest
from pathlib import Path

from league_bot.macro import MacroCancelled, MacroError, MacroRunner, load_macro, resolve_coord, validate_steps
from tests.fakes import FakeBackend, FakeTime

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Slayer Legend"
CLICK_CENTER = {"action": "click", "x": "center", "y": "center"}


def make_runner(backend, clock, foreground=True):
    return MacroRunner(backend, TITLE, foreground, sleep=clock.sleep, clock=clock.clock)


class ResolveCoordTests(unittest.TestCase):
    def test_center_percent_and_absolute(self):
        self.assertEqual(resolve_coord("center", 801), 400)
        self.assertEqual(resolve_coord("47.8%", 400), 191)
        self.assertEqual(resolve_coord("82.5%", 800), 660)
        self.assertEqual(resolve_coord(15, 800), 15)
        self.assertEqual(resolve_coord(15.9, 800), 15)

    def test_invalid_values(self):
        for bad in ("TODO%", "abc", True, None, [1]):
            with self.assertRaises(MacroError):
                resolve_coord(bad, 100)


class ValidateTests(unittest.TestCase):
    def test_rejects_malformed_macros(self):
        cases = [
            [],
            "not a list",
            ["not an object"],
            [{"action": "teleport"}],
            [{"action": "click", "x": 1}],
            [{"action": "click", "x": "TODO%", "y": 1}],
            [{"action": "wait_for_pixel", "x": 1, "y": 1, "color": [1, 2]}],
            [{"action": "wait_for_pixel", "x": 1, "y": 1, "color": [1, 2, 300]}],
            [{"action": "move_resize", "width": 10}],
        ]
        for steps in cases:
            with self.subTest(steps=steps), self.assertRaises(MacroError):
                validate_steps(steps)

    def test_error_names_the_step(self):
        with self.assertRaisesRegex(MacroError, "step 2"):
            validate_steps([{"action": "wait"}, {"action": "nope"}])

    def test_shipped_macros_are_valid(self):
        files = sorted((ROOT / "macros").glob("*.json"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(macro=path.name):
                self.assertTrue(load_macro(path))

    def test_load_accepts_plain_list_and_rejects_bad_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps([{"action": "wait"}]), encoding="utf-8")
            self.assertEqual(load_macro(good), [{"action": "wait"}])
            bad = Path(tmp) / "bad.json"
            bad.write_text("{oops", encoding="utf-8")
            with self.assertRaisesRegex(MacroError, "invalid JSON"):
                load_macro(bad)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.clock = FakeTime()

    def run_steps(self, steps, **kwargs):
        make_runner(self.backend, self.clock, **kwargs).run(steps)

    def test_click_uses_window_relative_coordinates_and_foreground_flag(self):
        self.run_steps([CLICK_CENTER], foreground=True)
        self.run_steps([{"action": "click", "x": "10%", "y": 5}], foreground=False)
        self.assertEqual(self.backend.clicks(), [(200, 400, True), (40, 5, False)])

    def test_wait_window_polls_until_the_window_appears(self):
        self.backend.hide_for = 3
        self.run_steps([{"action": "wait_window", "timeout": 10}])
        self.assertEqual(self.clock.sleeps, [1.0, 1.0, 1.0])

    def test_wait_window_times_out(self):
        self.backend.hide_for = 10_000
        with self.assertRaisesRegex(MacroError, "did not appear"):
            self.run_steps([{"action": "wait_window", "timeout": 3}])
        self.assertGreaterEqual(self.clock.now, 3)

    def test_click_without_window_fails(self):
        self.backend.hide_for = 10_000
        with self.assertRaisesRegex(MacroError, "not found"):
            self.run_steps([CLICK_CENTER])

    def test_wait_for_pixel_matches_after_the_color_changes(self):
        self.backend.frames = [(0, 0, 0), (230, 230, 230)]
        step = {"action": "wait_for_pixel", "x": "50%", "y": "50%", "color": [230, 230, 230],
                "tolerance": 10, "poll_seconds": 0.5, "timeout": 5}
        self.run_steps([step])
        self.assertEqual(self.backend.calls.count(("capture",)), 2)

    def test_wait_for_pixel_times_out(self):
        step = {"action": "wait_for_pixel", "x": 1, "y": 1, "color": [255, 0, 0], "poll_seconds": 1, "timeout": 3}
        with self.assertRaisesRegex(MacroError, "did not appear"):
            self.run_steps([step])

    def test_click_if_pixel_clicks_exactly_where_it_matched(self):
        self.backend.fill = (237, 138, 0)
        step = {"action": "click_if_pixel", "x": "31.8%", "y": "78.15%", "color": [237, 138, 0], "tolerance": 20, "timeout": 2}
        self.run_steps([step])
        self.assertEqual(self.backend.clicks(), [(127, 625, True)])

    def test_click_if_pixel_continues_when_nothing_matches(self):
        step = {"action": "click_if_pixel", "x": 5, "y": 5, "color": [237, 138, 0], "poll_seconds": 0.5, "timeout": 2}
        self.run_steps([step, {"action": "minimize"}])
        self.assertEqual(self.backend.clicks(), [])
        self.assertIn(("minimize",), self.backend.calls)
        self.assertGreaterEqual(self.clock.now, 2)

    def test_move_resize_position_is_optional(self):
        self.run_steps([{"action": "move_resize", "width": 438, "height": 814},
                        {"action": "move_resize", "x": 10, "y": 20, "width": 300, "height": 400}])
        self.assertEqual(self.backend.calls, [("move_resize", None, None, 438, 814), ("move_resize", 10, 20, 300, 400)])

    def test_cancel_during_a_wait_stops_before_the_next_step(self):
        holder = {}

        def sleep(_seconds):
            holder["runner"].cancel()

        runner = MacroRunner(self.backend, TITLE, True, sleep=sleep, clock=self.clock.clock)
        holder["runner"] = runner
        with self.assertRaises(MacroCancelled):
            runner.run([{"action": "wait", "seconds": 5}, CLICK_CENTER])
        self.assertEqual(self.backend.clicks(), [])

    def test_handle_is_re_resolved_when_the_window_is_recreated(self):
        def recreate_window(_seconds):
            self.backend.hwnd = 202  # splash window destroyed, main window created

        runner = MacroRunner(self.backend, TITLE, True, sleep=recreate_window, clock=self.clock.clock)
        runner.run([CLICK_CENTER, {"action": "wait", "seconds": 1}, CLICK_CENTER])
        self.assertEqual([hwnd for hwnd, *_ in self.backend.click_log], [101, 202])

    def test_shipped_start_game_macro_end_to_end(self):
        self.backend.fill = (230, 230, 230)  # "TAP TO START" lit; no orange Confirm button
        steps = load_macro(ROOT / "macros" / "start_game.json")
        self.run_steps(steps)
        self.assertEqual(self.backend.clicks(), [(200, 400, True)] * 5)
        self.assertEqual(self.backend.calls[-2:], [("move_resize", None, None, 438, 814), ("minimize",)])


if __name__ == "__main__":
    unittest.main()
