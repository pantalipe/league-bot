import json
import tempfile
import unittest
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from league_bot.macro import MacroCancelled
from league_bot.slayer.macro_sequence import MacroSequence, SequenceError


class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 10, 16, 12, tzinfo=timezone(timedelta(hours=-3)))
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)


class FakeLibrary:
    def __init__(self, macros):
        self.macros = macros

    def names(self):
        return list(self.macros)

    def load_steps(self, name):
        return self.macros[name]


class FakeRunner:
    def __init__(self, elapsed=0):
        self.calls = []
        self.elapsed = elapsed
        self.cancelled = False

    def run(self, steps, name="macro"):
        self.calls.append((name, steps))

    def cancel(self):
        self.cancelled = True


def recording(*actions):
    return [{"action": action, **values} for action, values in actions]


class MacroSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "sequence.json"
        self.clock = FakeClock()

    def sequence(self, macros, selected=None, runner=None, **kwargs):
        return MacroSequence(
            FakeLibrary(macros), runner or FakeRunner(), self.state,
            selected_names=selected, clock=self.clock.now, sleep=self.clock.sleep,
            **kwargs,
        )

    def test_preflight_converts_pixel_waits_without_mutating_recording(self):
        source = [{"action": "wait_for_pixel", "x": 4, "y": 5, "color": [1, 2, 3], "timeout": 20},
                  {"action": "click", "x": 10, "y": 20}]
        sequence = self.sequence({"sample": source}, ["sample"], extra_delay=(0, 0))
        steps = sequence.preflight()["sample"]
        self.assertEqual(steps[0], {"action": "wait", "seconds": 0.5})
        self.assertEqual(source[0]["action"], "wait_for_pixel")
        self.assertEqual(steps[1]["action"], "click")

    def test_ambiguous_and_visual_actions_fail_before_any_macro_runs(self):
        for action, fields in (("click_if_pixel", {"x": 1, "y": 2, "color": [0, 0, 0]}),
                               ("screen_flow", {"screens": [], "terminal": "done"})):
            runner = FakeRunner()
            sequence = self.sequence({"bad": [{"action": action, **fields}]}, ["bad"], runner)
            with self.assertRaises(SequenceError):
                sequence.run()
            self.assertEqual(runner.calls, [])

    def test_random_delay_is_added_before_each_click_and_recorded_wait_is_preserved(self):
        runner = FakeRunner()
        sequence = self.sequence(
            {"task": [{"action": "wait", "seconds": 7}, {"action": "click", "x": 1, "y": 2}]},
            ["task"], runner, extra_delay=(0.2, 0.2),
        )
        sequence.run()
        steps = runner.calls[0][1]
        self.assertEqual(steps[0], {"action": "wait", "seconds": 7})
        self.assertEqual(steps[1], {"action": "wait", "seconds": 0.2})
        self.assertEqual(steps[2]["action"], "click")

    def test_repeat_cooldown_and_execution_counts_persist(self):
        runner = FakeRunner()
        sequence = self.sequence({"blorb": [{"action": "wait", "seconds": 1}]}, ["blorb"], runner)
        result = sequence.run()
        self.assertEqual(len(runner.calls), 3)
        self.assertGreaterEqual(sum(self.clock.sleeps), 600)
        self.assertEqual(len(result["executions"]["blorb"]), 3)
        saved = json.loads(self.state.read_text())
        self.assertIsNone(saved["in_progress"])
        resumed = self.sequence({"blorb": [{"action": "wait", "seconds": 1}]}, ["blorb"], FakeRunner())
        self.assertTrue(resumed.run()["completed"])

    def test_finished_collection_is_last_and_refinement_waits_ten_minutes(self):
        names = ["refinamento_skill", "refinamento_skill_completed", "cobinar_equip",
                 "free_wpacs", "beast_colletct_free", "collect_familiar", "pet_guild",
                 "collect_finished_dailys"]
        macros = {name: [{"action": "wait", "seconds": 1}] for name in names}
        runner = FakeRunner()
        sequence = self.sequence(macros, names, runner)
        sequence.run()
        ran = [name for name, _ in runner.calls]
        self.assertEqual(ran[-1], "collect_finished_dailys")
        self.assertGreaterEqual(ran.index("refinamento_skill_completed"), 0)
        self.assertTrue(any(seconds >= 600 for seconds in self.clock.sleeps))

    def test_interrupted_macro_is_not_replayed_on_resume(self):
        class FailingRunner(FakeRunner):
            def run(self, steps, name="macro"):
                raise RuntimeError("stopped mid-recording")

        sequence = self.sequence({"task": [{"action": "click", "x": 1, "y": 1}]}, ["task"], FailingRunner())
        with self.assertRaises(RuntimeError):
            sequence.run()
        self.assertEqual(json.loads(self.state.read_text())["in_progress"], "task")
        with self.assertRaisesRegex(SequenceError, "interrupted"):
            self.sequence({"task": [{"action": "click", "x": 1, "y": 1}]}, ["task"]).run()
        recovered = self.sequence({"task": [{"action": "click", "x": 1, "y": 1}]}, ["task"])
        self.assertEqual(recovered.acknowledge_interruption(), "task")
        self.assertTrue(recovered.run()["completed"])

    def test_cycle_resets_at_0200_local(self):
        self.clock.value = datetime(2026, 10, 16, 1, 59, tzinfo=timezone(timedelta(hours=-3)))
        sequence = self.sequence({"task": [{"action": "wait", "seconds": 1}]}, ["task"])
        self.assertEqual(sequence.run()["cycle"], "2026-10-15")

    def test_different_seeds_change_eligible_order(self):
        orders = set()
        for seed in range(8):
            path = Path(self.temp.name) / f"seed-{seed}.json"
            runner = FakeRunner()
            names = ["a", "b", "c"]
            sequence = MacroSequence(
                FakeLibrary({n: [{"action": "wait", "seconds": 1}] for n in names}),
                runner, path, selected_names=names, rng=random.Random(seed), clock=self.clock.now,
            )
            sequence.run()
            orders.add(tuple(n for n, _ in runner.calls))
        self.assertGreater(len(orders), 1)

    def test_cancel_during_cooldown_stops_further_runs(self):
        runner = FakeRunner()
        sequence = self.sequence({"blorb": [{"action": "wait", "seconds": 1}]}, ["blorb"], runner)
        sequence.sleep = lambda seconds: sequence.cancel()
        with self.assertRaises(MacroCancelled):
            sequence.run()
        self.assertEqual(len(runner.calls), 1)
        self.assertTrue(runner.cancelled)

    def test_free_summons_and_refinement_honor_separate_intervals(self):
        names = ["free_wpacs", "refinamento_skill", "refinamento_skill_completed"]
        class TimedRunner(FakeRunner):
            def run(inner, steps, name="macro"):
                inner.calls.append((name, self.clock.now()))
        runner = TimedRunner()
        sequence = self.sequence({n: [{"action": "wait", "seconds": 1}] for n in names}, names, runner)
        sequence.run()
        summons = [when for name, when in runner.calls if name == "free_wpacs"]
        self.assertEqual(len(summons), 3)
        self.assertTrue(all((b-a).total_seconds() >= 600 for a, b in zip(summons, summons[1:])))
        times = dict(runner.calls)
        self.assertGreaterEqual((times["refinamento_skill_completed"] - times["refinamento_skill"]).total_seconds(), 600)

    def test_default_excludes_battles_and_buffs(self):
        from league_bot.slayer.plan import MACRO_CATALOG, ACTIVATIONS
        from league_bot.slayer.macro_sequence import BLOCKED
        macros = {n: [{"action": "wait", "seconds": 1}] for n in MACRO_CATALOG}
        prepared = self.sequence(macros).preflight()
        self.assertFalse(set(prepared) & (set(BLOCKED) | set(ACTIVATIONS)))

    def test_real_runner_never_captures_for_converted_recording(self):
        from league_bot.macro import MacroRunner
        from tests.fakes import FakeBackend
        class NoCaptureBackend(FakeBackend):
            def capture(self, hwnd):
                raise AssertionError("recognition must not capture")
        backend = NoCaptureBackend()
        runner = MacroRunner(backend, backend.TITLE, sleep=lambda seconds: None)
        steps = [{"action": "wait_for_pixel", "x": 1, "y": 1, "color": [0, 0, 0]},
                 {"action": "click", "x": 10, "y": 20}]
        sequence = self.sequence({"task": steps}, ["task"], runner)
        sequence.run()
        self.assertEqual(len(backend.click_log), 1)

    def test_cycle_change_during_wait_stops_without_next_clicks(self):
        self.clock.value = datetime(2026, 10, 16, 1, 59, tzinfo=timezone(timedelta(hours=-3)))
        runner = FakeRunner()
        sequence = self.sequence({"blorb": [{"action": "wait", "seconds": 1}]}, ["blorb"], runner)
        result = sequence.run()
        self.assertFalse(result["completed"])
        self.assertEqual(result["reason"], "cycle_changed")
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
