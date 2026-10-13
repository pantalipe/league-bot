"""Fixture-backed tests for read-only free-summon quota observation."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from tests.fakes import FakeBackend, FakeTime

try:
    from test_slayer_attendance import png_frame
    _HAS_IMAGES = True
except ModuleNotFoundError:
    _HAS_IMAGES = False

if la.available():
    from league_bot.imaging import Frame
    from league_bot.macro import MacroCancelled, MacroRunner
    from league_bot.slayer.status import DailyStatusStore
    from league_bot.slayer.summons import (
        SummonRunner, observation_step, profiles, read_summons,
        record_summons, run_summons,
    )


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "summons"
COUNTS = {"weapon": "summon_sword", "accessory": "summon_accessory", "skill": "summon_skill"}


def summon_frame(kind: str, used: int):
    return png_frame(FIXTURES / f"{kind}-{used}.png")


class FrameBackend(FakeBackend):
    def __init__(self, frames, *, size=(434, 810)):
        super().__init__(size=size)
        self.scripted_frames = list(frames)

    def capture(self, hwnd):
        self.calls.append(("capture",))
        if len(self.scripted_frames) > 1:
            return self.scripted_frames.pop(0)
        return self.scripted_frames[0]


class FakeStatus:
    def __init__(self, cycle="2026-10-13"):
        self.cycle = cycle
        self.tasks = {}
        self.records = []

    def cycle_id(self):
        return self.cycle

    def snapshot(self):
        return {"tasks": copy.deepcopy(self.tasks)}

    def mark_progress(self, task_id, progress, target, **kwargs):
        self.records.append((task_id, progress, target, kwargs))
        task = self.tasks.setdefault(task_id, {"progress": 0})
        task.update(progress=progress, target=target, source=kwargs.get("source"), last_error=None)


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonReaderTests(unittest.TestCase):
    def test_all_labelled_counter_fixtures_read_as_used_counts(self):
        for kind, task in COUNTS.items():
            for used in (0, 1, 3):
                with self.subTest(kind=kind, used=used):
                    self.assertEqual(read_summons(summon_frame(kind, used)), {task: used})

    def test_wrong_panel_geometry_unfamiliar_bitmap_and_conflicting_templates_are_unknown(self):
        self.assertEqual(read_summons(png_frame(ROOT / "tests/fixtures/slayer/home/main.png")), {})
        original = summon_frame("skill", 1)
        self.assertEqual(read_summons(Frame(original.width - 1, original.height, original.bgr)), {})

        data = profiles()
        row = copy.deepcopy(data["counter_templates"]["panel"][1])
        row["used"] = 2
        data["counter_templates"]["panel"].append(row)
        self.assertEqual(read_summons(summon_frame("skill", 1), data), {})

        # A pixel change inside the calibrated counter must not be rounded to
        # the nearest supported digit mask.
        pixels = bytearray(original.bgr)
        stride = ((original.width * 3 + 3) // 4) * 4
        x, y = 400, 661
        offset = (original.height - 1 - y) * stride + x * 3
        pixels[offset:offset + 3] = bytes((0, 0, 0))
        self.assertEqual(read_summons(Frame(original.width, original.height, bytes(pixels))), {})


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonRecordingTests(unittest.TestCase):
    def test_visual_progress_never_reduces_a_higher_manual_count(self):
        status = FakeStatus()
        status.tasks["summon_sword"] = {"progress": 2, "source": "manual"}
        record_summons(status, {"summon_sword": 1}, status.cycle_id())
        self.assertEqual(status.records, [])

    def test_equal_visual_progress_is_not_written_again(self):
        status = FakeStatus()
        status.tasks["summon_skill"] = {"progress": 1, "source": "visual", "last_error": None}
        record_summons(status, {"summon_skill": 1}, status.cycle_id())
        self.assertEqual(status.records, [])

    def test_cycle_change_refuses_to_record_stale_observation(self):
        status = FakeStatus()
        expected = status.cycle_id()
        status.cycle = "2026-10-14"
        with self.assertRaises(MacroCancelled):
            record_summons(status, {"summon_accessory": 1}, expected)
        self.assertEqual(status.records, [])

    def test_real_store_manual_higher_progress_survives_visual_observation(self):
        now = [datetime(2026, 10, 13, 12, tzinfo=timezone(timedelta(hours=-3)))]
        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStatusStore(Path(tmp) / "daily.json", now=lambda: now[0])
            cycle = store.cycle_id()
            store.mark_progress("summon_sword", 2, 3, source="manual")
            record_summons(store, {"summon_sword": 1}, cycle)
            self.assertEqual(store.snapshot()["tasks"]["summon_sword"]["progress"], 2)
            self.assertEqual(store.snapshot()["tasks"]["summon_sword"]["source"], "manual")


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonObserverTests(unittest.TestCase):
    def make_runner(self, frames, *, status=None, time=None):
        self.time = time or FakeTime()
        self.backend = FrameBackend(frames)
        self.runner = SummonRunner(
            self.backend, "Slayer Legend", foreground=True,
            sleep=self.time.sleep, clock=self.time.clock,
            store=status, cycle=status.cycle_id() if status else None,
        )
        return self.runner

    def test_stable_known_observation_records_used_count_without_clicking(self):
        status = FakeStatus()
        runner = self.make_runner([summon_frame("skill", 1)], status=status)
        runner.run([observation_step("summon_skill")])
        self.assertEqual(status.records[0][0:3], ("summon_skill", 1, 3))
        self.assertEqual(self.backend.clicks(), [])

    def test_unfamiliar_screen_times_out_unknown_without_false_completion_or_click(self):
        status = FakeStatus()
        unknown = png_frame(ROOT / "tests/fixtures/slayer/home/main.png")
        runner = self.make_runner([unknown], status=status)
        runner.run([observation_step("summon_skill")])
        self.assertEqual(status.records, [])
        self.assertEqual(self.backend.clicks(), [])

    def test_cancellation_and_cycle_rollover_stop_observation_without_clicks(self):
        runner = self.make_runner([summon_frame("skill", 1)])
        runner.cancel()
        with self.assertRaises(MacroCancelled):
            runner.run([observation_step("summon_skill")])
        self.assertEqual(self.backend.clicks(), [])

        status = FakeStatus()
        clock = FakeTime()
        class RolloverTime(FakeTime):
            def sleep(inner, seconds):
                super(RolloverTime, inner).sleep(seconds)
                status.cycle = "2026-10-14"
        clock = RolloverTime()
        runner = self.make_runner([summon_frame("skill", 1)], status=status, time=clock)
        with self.assertRaises(MacroCancelled):
            runner.run([observation_step("summon_skill")])
        self.assertEqual(status.records, [])
        self.assertEqual(self.backend.clicks(), [])

    def test_run_factory_is_restored_after_macro_failure(self):
        class GameStub:
            def __init__(self):
                self._runner_factory = lambda *args: MacroRunner(*args)
                self.original_factory = self._runner_factory
                self._status_store = FakeStatus()
                self.entered = False
            @contextmanager
            def _exclusive(self):
                yield
            def load_macro_steps(self, name):
                self.asserted_name = name
                return []
            def _title(self):
                return "Slayer Legend"
            def _run_steps(self, *args):
                self.entered = True
                raise RuntimeError("macro failed")
        game = GameStub()
        with self.assertRaisesRegex(RuntimeError, "macro failed"):
            run_summons(game)
        self.assertTrue(game.entered)
        self.assertIs(game._runner_factory, game.original_factory)
