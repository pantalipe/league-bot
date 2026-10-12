"""Guarded, fixture-backed tests for the free Slayer cube mission flow."""
from __future__ import annotations

import copy
from functools import lru_cache
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from league_bot.slayer.status import DailyStatusStore

if la.available():
    from league_bot.slayer.cube import TASK, cube_steps, load_screens
    from league_bot.backend import InputSample
    from league_bot.imaging import Frame
    from league_bot.macro import MacroCancelled, MacroError, MacroRunner
    from league_bot.screens import matching_screens

from test_slayer_attendance import FakeBackend, FakeTime, png_frame


WIDTH, HEIGHT = 434, 810
FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "cube"


@lru_cache(maxsize=None)
def cube_frame(name: str):
    return png_frame(FIXTURES / f"{name}.png")


def flow_frame(name):
    if name in {'adventure','dungeon'}:
        return png_frame(ROOT / f'tests/fixtures/slayer/guild_navigation/map_{name}.png')
    return cube_frame(name)


def png_image_frame(image: Image.Image):
    """Convert an in-memory RGB image to the same bottom-up BGR Frame layout."""
    image = image.convert("RGB")
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


def repeat(frame, count=2):
    return [frame] * count


def current_flow_frames(states):
    states = list(states)
    if "dungeon" in states:
        index = states.index("dungeon")
        states[index:index] = ["dungeon", "dungeon"]
    return [flow_frame(state) for state in states]


def standard_flow_frames():
    """Two stable observations per state, including a loading interval."""
    states = [
        "main", "main", "adventure", "dungeon", "dungeon", "rift_free", "rift_free",
        "multiplier", "loading", "rift_exhausted", "rift_exhausted",
        "dungeon", "main",
    ]
    return [flow_frame(name) for name in states for _ in range(2)]


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class CubeProfileTests(unittest.TestCase):
    def test_fixture_states_match_only_their_named_profile(self):
        screens = load_screens()
        expected = {
            "main": "main",
            "adventure": "adventure",
            "dungeon": "dungeon",
            "rift_free": "rift_free",
            "multiplier": "multiplier",
            "rift_exhausted": "rift_exhausted",
        }
        for fixture, state in expected.items():
            with self.subTest(state=state):
                self.assertEqual(matching_screens(cube_frame(fixture), screens), [state])

        # The title-only guard is intentionally weaker than the complete free counter.
        free = next(screen for screen in screens if screen["name"] == "rift_free")
        rift_open = copy.deepcopy(free)
        rift_open["name"] = "rift_open"
        rift_open["anchors"] = rift_open["anchors"][:14]
        rift_open.pop("click", None)
        self.assertEqual(matching_screens(cube_frame("rift_free"), [rift_open]), ["rift_open"])
        self.assertEqual(matching_screens(cube_frame("rift_exhausted"), [rift_open]), ["rift_open"])

        self.assertEqual(matching_screens(cube_frame("loading"), screens), [])
        # Returned-main is a separate fixture capture of the same stable main state.
        self.assertEqual(matching_screens(cube_frame("returned_main"), screens), ["main"])

    def test_corrupt_free_counter_is_title_only_and_cannot_match_free_entry(self):
        screens = load_screens()
        free = next(screen for screen in screens if screen["name"] == "rift_free")
        # Damage a counter anchor while preserving the title-only rift_open anchors.
        anchor = next(a for a in reversed(free["anchors"][14:])
                      if a["y"] > 0.3 and all(
                          abs(a["x"] - prior["x"]) > 0.002 or abs(a["y"] - prior["y"]) > 0.002
                          for prior in free["anchors"][:14]
                      ))
        image = Image.open(FIXTURES / "rift_free.png").convert("RGB")
        x = round(anchor["x"] * (image.width - 1))
        y = round(anchor["y"] * (image.height - 1))
        expected = anchor["color"]
        image.putpixel((x, y), (0, 0, 0) if max(expected) > 128 else (255, 255, 255))
        damaged = png_image_frame(image)

        title_guard = copy.deepcopy(free)
        title_guard["name"] = "rift_open"
        title_guard["anchors"] = title_guard["anchors"][:14]
        self.assertEqual(matching_screens(damaged, [title_guard]), ["rift_open"])
        self.assertEqual(matching_screens(damaged, screens), [])


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class CubeFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="slayer-cube-test-")
        self.addCleanup(self.temp.cleanup)
        self.time = FakeTime()
        self.backend = FakeBackend()
        self.now = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        self.store = DailyStatusStore(
            Path(self.temp.name) / "daily-status.json",
            now=lambda: self.now,
        )
        settings = SimpleNamespace(
            window_title="Slayer Legend", foreground_input=True,
            macros_dir=Path(self.temp.name) / "macros", data_dir=Path(self.temp.name) / "data",
            process_names=("SlayerLegend.exe",), start_macro="start_game_recognized",
        )
        self.game = la.HomeSlayerGame(
            settings, self.backend, status_store=self.store,
            launcher=lambda _settings: None,
            runner_factory=lambda backend, title, foreground, log: MacroRunner(
                backend, title, foreground, log, sleep=self.time.sleep, clock=self.time.clock,
            ),
        )

    def progress(self):
        return self.store.snapshot()["tasks"][TASK]

    def run_with_short_timeout(self, frames, *, timeout=1.2, short_terminal="rift_exhausted"):
        self.backend.frames = list(frames)
        original = cube_steps

        def shortened():
            steps = original()
            for step in steps:
                if step.get("action") == "screen_flow" and step.get("terminal") == short_terminal:
                    step["timeout"] = min(step["timeout"], timeout)
            return steps

        with mock.patch("league_bot.slayer.cube.cube_steps", side_effect=shortened):
            return self.game.run_macro("cubo_de_melhora")

    def test_free_run_recognizes_stable_states_and_returns_to_main(self):
        self.backend.frames = standard_flow_frames()

        result = self.game.run_macro("cubo_de_melhora")

        self.assertIn("3/3", result)
        self.assertEqual(self.backend.click_log, [
            (331, 784, False),  # main -> adventure
            (185, 107, False),  # adventure -> dungeon
            (282, 422, False),  # dungeon -> rift
            (230, 664, False),  # free entry
            (346, 584, False),  # x3 multiplier
            (45, 775, False),   # exhausted rift -> dungeon map
            (325, 784, False),  # map -> main
        ])
        self.assertTrue(any(call[:5] == ("move_resize", 1460, 202, 438, 814)
                            for call in self.backend.calls))
        self.assertIn(("minimize",), self.backend.calls)
        task = self.progress()
        self.assertEqual((task["progress"], task["target"], task["status"], task["source"]),
                         (3, 3, "completed", "visual"))

    def test_already_exhausted_free_entries_only_leave_the_rift_and_mark_three(self):
        states = ["main", "main", "main", "main", "adventure", "adventure", "dungeon", "dungeon",
                  "rift_exhausted", "rift_exhausted", "rift_exhausted", "rift_exhausted",
                  "rift_exhausted", "rift_exhausted",
                  "dungeon", "dungeon", "main", "main"]
        self.backend.frames = current_flow_frames(states)

        result = self.game.run_macro("cubo_de_melhora")

        self.assertIn("ja esgotadas", result)
        self.assertEqual(self.backend.click_log, [
            (331, 784, False), (185, 107, False), (282, 422, False),
            (45, 775, False), (325, 784, False),
        ])
        self.assertEqual((self.progress()["progress"], self.progress()["status"]), (3, "completed"))

    def test_unknown_counter_after_title_guard_times_out_without_enter_or_x3(self):
        screens = load_screens()
        free = next(screen for screen in screens if screen["name"] == "rift_free")
        anchor = next(a for a in reversed(free["anchors"][14:])
                      if a["y"] > 0.3 and all(
                          abs(a["x"] - prior["x"]) > 0.002 or abs(a["y"] - prior["y"]) > 0.002
                          for prior in free["anchors"][:14]
                      ))
        image = Image.open(FIXTURES / "rift_free.png").convert("RGB")
        x, y = round(anchor["x"] * (image.width - 1)), round(anchor["y"] * (image.height - 1))
        image.putpixel((x, y), (0, 0, 0) if max(anchor["color"]) > 128 else (255, 255, 255))
        partial = png_image_frame(image)
        frames = [cube_frame("main"), cube_frame("main"), cube_frame("main"), cube_frame("main"),
                  flow_frame("adventure"), flow_frame("adventure"),
                  flow_frame("dungeon"), flow_frame("dungeon"),
                  partial, partial]

        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            self.run_with_short_timeout(frames)

        self.assertNotIn((230, 664, False), self.backend.click_log)
        self.assertNotIn((346, 584, False), self.backend.click_log)
        self.assertEqual(self.progress()["progress"], 0)

    def test_stalled_multiplier_modal_gets_only_one_bounded_retry(self):
        frames = [cube_frame("main"), cube_frame("main"), cube_frame("main"), cube_frame("main"),
                  flow_frame("adventure"), flow_frame("adventure"),
                  flow_frame("dungeon"), flow_frame("dungeon"),
                  cube_frame("rift_free"), cube_frame("rift_free"),
                  cube_frame("rift_free"), cube_frame("rift_free"),
                  *([cube_frame("multiplier")] * 100)]

        with self.assertRaisesRegex(MacroError, "timed out.*multiplier"):
            self.run_with_short_timeout(frames, timeout=14)

        self.assertEqual(self.backend.click_log.count((230, 664, False)), 1)
        self.assertEqual(self.backend.click_log.count((346, 584, False)), 2)
        self.assertEqual(self.progress()["progress"], 0)

    def test_multiplier_retry_that_reaches_loading_finishes_without_more_clicks(self):
        frames = [cube_frame(name) for name in [
            "main", "main", "main", "main", "adventure", "adventure", "dungeon", "dungeon",
            "rift_free", "rift_free", "rift_free", "rift_free",
        ]]
        frames.extend([cube_frame("multiplier")] * 100)
        original_click = self.backend.click

        def advance_after_retry(hwnd, x, y, foreground):
            original_click(hwnd, x, y, foreground)
            if (x, y) == (346, 584) and self.backend.click_log.count((346, 584, foreground)) == 2:
                self.backend.frames = [cube_frame("loading")] * 2
                self.backend.frames += [cube_frame("rift_exhausted")] * 4
                self.backend.frames += [flow_frame("dungeon")] * 2
                self.backend.frames += [cube_frame("main")] * 2

        self.backend.click = advance_after_retry

        result = self.run_with_short_timeout(frames, timeout=14)

        self.assertIn("3/3", result)
        self.assertEqual(self.backend.click_log.count((230, 664, False)), 1)
        self.assertEqual(self.backend.click_log.count((346, 584, False)), 2)
        self.assertEqual(self.progress()["progress"], 3)

    def test_error_after_exhausted_terminal_keeps_three_progress(self):
        # The exhausted state is stable and credited before the cleanup flow fails.
        frames = [cube_frame(name) for name in [
            "main", "main", "main", "main", "adventure", "adventure", "dungeon", "dungeon",
            "rift_free", "rift_free", "rift_free", "rift_free",
            "multiplier", "multiplier", "loading", "loading",
            "rift_exhausted", "rift_exhausted", "rift_exhausted", "rift_exhausted",
        ]]
        unknown = png_image_frame(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)))
        frames.extend([unknown, unknown])
        with self.assertRaisesRegex(MacroError, "timed out.*unknown"):
            self.run_with_short_timeout(frames, short_terminal="main")

        task = self.progress()
        self.assertEqual((task["progress"], task["target"], task["status"], task["source"]),
                         (3, 3, "completed", "visual"))
        self.assertTrue(task["last_error"])

    def test_cancel_after_exhaustion_keeps_progress_without_marking_error(self):
        self.backend.frames = standard_flow_frames()
        progress_saved = False
        original_mark = self.store.mark_progress
        original_capture = self.backend.capture

        def mark_progress(task_id, *args, **kwargs):
            nonlocal progress_saved
            result = original_mark(task_id, *args, **kwargs)
            if task_id == TASK:
                progress_saved = True
            return result

        def cancel_after_progress(hwnd):
            if progress_saved:
                raise MacroCancelled("test cancellation after stable exhausted state")
            return original_capture(hwnd)

        with mock.patch.object(self.store, "mark_progress", side_effect=mark_progress), \
             mock.patch.object(self.backend, "capture", side_effect=cancel_after_progress):
            with self.assertRaises(MacroCancelled):
                self.game.run_macro("cubo_de_melhora")

        task = self.progress()
        self.assertEqual((task["progress"], task["status"]), (3, "completed"))
        self.assertIsNone(task["last_error"])

    def test_daily_reset_during_run_does_not_write_old_cycle_progress(self):
        self.backend.frames = standard_flow_frames()
        original_click = self.backend.click

        def cross_daily_reset_after_multiplier(hwnd, x, y, foreground):
            original_click(hwnd, x, y, foreground)
            if (x, y) == (346, 584):
                self.now = datetime(2026, 10, 11, 2, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

        self.backend.click = cross_daily_reset_after_multiplier

        self.game.run_macro("cubo_de_melhora")

        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["cycle_id"], "2026-10-11")
        task = snapshot["tasks"][TASK]
        self.assertEqual((task["progress"], task["status"]), (0, "not_checked"))


if __name__ == "__main__":
    unittest.main()
