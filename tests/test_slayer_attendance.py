"""Real screen-flow and startup integration tests for the calibrated attendance modal."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
if la.available():
    from league_bot.backend import InputSample
    from league_bot.game import GameBusy, SlayerGame
    from league_bot.imaging import Frame, solid_frame
    from league_bot.macro import MacroError, MacroRunner
    from league_bot.screens import matching_screens


WIDTH, HEIGHT = 434, 810
FIXTURES = ROOT / "tests" / "fixtures" / "slayer"


def png_frame(path: Path) -> Frame:
    """Convert the sanitized RGB fixture into the Frame layout used by Win32 capture."""
    image = Image.open(path).convert("RGB")
    width, height = image.size
    row_size = ((width * 3 + 3) // 4) * 4
    rgb = image.tobytes()
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        start = y * width * 3
        for offset in range(start, start + width * 3, 3):
            row.extend((rgb[offset + 2], rgb[offset + 1], rgb[offset]))
        row.extend(b"\x00" * (row_size - width * 3))
        pixels.extend(row)
    return Frame(width, height, bytes(pixels))


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeBackend:
    """Small deterministic window backend that consumes captured Frames in order."""
    def __init__(self, frames=(), *, present=True, size=(WIDTH, HEIGHT)):
        self.frames = list(frames)
        self.present = present
        self.size = size
        self.hwnd = 7
        self.calls = []
        self.click_log = []
        self.minimized = False

    def find_window(self, title):
        self.calls.append(("find_window", title))
        return self.hwnd if self.present else None

    def is_window(self, hwnd):
        return self.present and hwnd == self.hwnd

    def client_size(self, hwnd):
        return self.size

    def is_minimized(self, hwnd):
        return self.minimized

    def capture(self, hwnd):
        self.calls.append(("capture",))
        if not self.frames:
            return None
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def click(self, hwnd, x, y, foreground):
        self.calls.append(("click", x, y, foreground))
        self.click_log.append((x, y, foreground))

    def restore(self, hwnd):
        self.calls.append(("restore",))
        self.minimized = False

    def minimize(self, hwnd):
        self.calls.append(("minimize",))
        self.minimized = True

    def move_resize(self, hwnd, x, y, width, height):
        self.calls.append(("move_resize", x, y, width, height))

    def poll_input(self, hwnd, stop_vk):
        return InputSample(0, 0, False, False, False)


def attendance_flow(*, timeout=6, screens=None):
    configured = la.load_attendance_screens()
    main = {
        "name": "main",
        "anchors": [
            {"x": 0.1, "y": 0.1, "color": [1, 2, 3], "tolerance": 0},
            {"x": 0.9, "y": 0.9, "color": [1, 2, 3], "tolerance": 0},
        ],
    }
    return {
        "action": "screen_flow",
        "terminal": "main",
        "timeout": timeout,
        "poll_seconds": 0.5,
        "stable_frames": 2,
        "frame_size": [WIDTH, HEIGHT],
        "screens": (screens if screens is not None else configured) + [main],
    }


def fixture_frames(*names):
    return [png_frame(FIXTURES / f"attendance-{name}.png") for name in names]


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class AttendanceScreenFlowTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.backend = FakeBackend()
        self.runner = MacroRunner(
            self.backend, "Slayer Legend", foreground=True,
            sleep=self.time.sleep, clock=self.time.clock,
        )

    def test_claim_ready_then_claimed_closes_modal_and_reaches_main(self):
        self.backend.frames = fixture_frames("ready", "ready", "claimed", "claimed") + [
            solid_frame(WIDTH, HEIGHT, (1, 2, 3)), solid_frame(WIDTH, HEIGHT, (1, 2, 3)),
        ]
        self.assertEqual(matching_screens(self.backend.frames[0], la.load_attendance_screens()),
                         ["attendance_claim_ready"])
        self.assertEqual(matching_screens(self.backend.frames[2], la.load_attendance_screens()),
                         ["attendance_claimed"])

        self.runner.run([attendance_flow()])

        self.assertEqual(self.backend.click_log, [(217, 610, False), (217, 712, False)])

    def test_both_fixtures_match_only_their_state_in_full_default_startup_profile(self):
        settings = la.load_settings(
            environ={"SLAYER_WINDOW_TITLE": "Slayer Legend"}, env_file=None,
        )
        game = la.HomeSlayerGame(settings, backend=object())
        steps = game.load_macro_steps("start_game_recognized")
        flow = next(step for step in steps if step["action"] == "screen_flow")

        self.assertEqual(matching_screens(png_frame(FIXTURES / "attendance-ready.png"), flow["screens"]),
                         ["attendance_claim_ready"])
        self.assertEqual(matching_screens(png_frame(FIXTURES / "attendance-claimed.png"), flow["screens"]),
                         ["attendance_claimed"])

    def test_already_claimed_state_only_closes_modal(self):
        self.backend.frames = fixture_frames("claimed", "claimed") + [
            solid_frame(WIDTH, HEIGHT, (1, 2, 3)), solid_frame(WIDTH, HEIGHT, (1, 2, 3)),
        ]
        self.runner.run([attendance_flow()])
        self.assertEqual(self.backend.click_log, [(217, 712, False)])

    def test_persistent_claim_ready_is_clicked_once_then_times_out(self):
        ready = png_frame(FIXTURES / "attendance-ready.png")
        self.backend.frames = [ready]
        with self.assertRaisesRegex(MacroError, "timed out.*attendance_claim_ready"):
            self.runner.run([attendance_flow(timeout=2)])
        self.assertEqual(self.backend.click_log, [(217, 610, False)])

    def test_unknown_frames_without_main_or_attendance_do_not_click(self):
        self.backend.frames = [solid_frame(WIDTH, HEIGHT, (0, 0, 0))]
        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            self.runner.run([attendance_flow(timeout=1)])
        self.assertEqual(self.backend.click_log, [])

    def test_ambiguous_ready_recognition_stops_before_click(self):
        screens = la.load_attendance_screens()
        duplicate = copy.deepcopy(screens[0])
        duplicate["name"] = "duplicate_ready"
        screens.insert(0, duplicate)
        self.backend.frames = fixture_frames("ready")
        with self.assertRaisesRegex(MacroError, "ambiguous.*duplicate_ready.*attendance_claim_ready"):
            self.runner.run([attendance_flow(screens=screens)])
        self.assertEqual(self.backend.click_log, [])


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class HomeSlayerStartTests(unittest.TestCase):
    def make_game(self, backend):
        self.time = FakeTime()
        self.launches = []
        settings = SimpleNamespace(
            window_title="Slayer Legend", start_macro="start_game_recognized",
            foreground_input=True, macros_dir=Path(tempfile.gettempdir()) / "slayer-attendance-tests",
            data_dir=Path(tempfile.gettempdir()) / "slayer-attendance-tests-data",
            process_names=("SlayerLegend.exe",),
        )
        return la.HomeSlayerGame(
            settings, backend,
            launcher=lambda _settings: (self.launches.append("launch"), setattr(backend, "present", True)),
            runner_factory=lambda b, title, foreground, log: MacroRunner(
                b, title, foreground, log, sleep=self.time.sleep, clock=self.time.clock,
            ),
        )

    def run_steps(self, game, *, timeout=6):
        flow = attendance_flow(timeout=timeout)
        with mock.patch.object(game, "load_macro_steps", return_value=[flow]):
            return game.start()

    def test_startup_profile_merges_attendance_states_before_final_minimize(self):
        game = self.make_game(FakeBackend())
        startup = [attendance_flow(), {"action": "minimize"}]
        with mock.patch.object(SlayerGame, "load_macro_steps", return_value=startup):
            steps = game.load_macro_steps("start_game_recognized")
        flow = next(step for step in steps if step["action"] == "screen_flow")
        names = {screen["name"] for screen in flow["screens"]}
        self.assertTrue({"attendance_claim_ready", "attendance_claimed", "main"}.issubset(names))
        self.assertEqual(steps[-2], {"action": "move_resize", "x": 1460, "y": 202,
                                     "width": 438, "height": 814})
        self.assertEqual(steps[-1], {"action": "minimize"})
        self.assertEqual(len(startup[0]["screens"]), 3)  # base macro remains unmodified

    def test_existing_window_runs_real_recognition_flow_without_launcher(self):
        backend = FakeBackend(fixture_frames("ready", "ready", "claimed", "claimed") + [
            solid_frame(WIDTH, HEIGHT, (1, 2, 3)), solid_frame(WIDTH, HEIGHT, (1, 2, 3)),
        ])
        game = self.make_game(backend)
        self.run_steps(game)
        self.assertEqual(self.launches, [])
        self.assertEqual(backend.click_log, [(217, 610, False), (217, 712, False)])

    def test_start_reports_busy_without_running_another_macro(self):
        backend = FakeBackend()
        game = self.make_game(backend)
        self.assertTrue(game._busy.acquire(blocking=False))
        try:
            with mock.patch.object(game, "load_macro_steps", return_value=[attendance_flow()]):
                with self.assertRaises(GameBusy):
                    game.start()
        finally:
            game._busy.release()
        self.assertEqual(backend.calls, [])

    def test_missing_window_launches_then_runs_recognition(self):
        backend = FakeBackend(fixture_frames("claimed", "claimed") + [
            solid_frame(WIDTH, HEIGHT, (1, 2, 3)), solid_frame(WIDTH, HEIGHT, (1, 2, 3)),
        ], present=False)
        game = self.make_game(backend)
        self.run_steps(game)
        self.assertEqual(self.launches, ["launch"])
        self.assertEqual(backend.click_log, [(217, 712, False)])


if __name__ == "__main__":
    unittest.main()
