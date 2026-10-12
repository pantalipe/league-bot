from __future__ import annotations

import math
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from league_bot.config import Settings
from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner
from league_bot.slayer.game import SlayerDailyGame
from tests.fakes import FakeBackend, FakeTime


class FixedRng:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def uniform(self, low, high):
        self.calls.append((low, high))
        return self.value


class TimedBackend(FakeBackend):
    def __init__(self, clock, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.click_times = []
        self.events = []

    def click(self, hwnd, x, y, foreground):
        self.click_times.append(self.clock.clock())
        self.events.append("click")
        super().click(hwnd, x, y, foreground)


class SlayerPacingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = FakeTime()
        self.backend = TimedBackend(self.clock)
        self.runners = []

        def factory(backend, title, foreground, log):
            runner = MacroRunner(backend, title, foreground, log,
                                 sleep=self.clock.sleep, clock=self.clock.clock)
            self.runners.append(runner)
            return runner

        self.factory = factory
        self.game = SlayerDailyGame(
            Settings(window_title="Slayer Legend", macros_dir=Path(self.temp.name)),
            self.backend, runner_factory=factory, sleep=self.clock.sleep,
        )

    def test_click_adds_only_an_injected_delay_after_the_original_wait(self):
        rng = FixedRng(.4)
        self.game = SlayerDailyGame(self.game._settings, self.backend,
            runner_factory=self.factory, sleep=self.clock.sleep, action_rng=rng,
            click_delay_range=(.15, .65))
        self.game._run_steps([
            {"action": "wait", "seconds": 1.0},
            {"action": "click", "x": 30, "y": 40},
        ], "pacing", "Slayer Legend")
        self.assertEqual(self.clock.sleeps, [1.0, .4])
        self.assertEqual(self.backend.click_times, [1.4])
        self.assertEqual(rng.calls, [(.15, .65)])
        self.assertEqual(self.backend.clicks(), [(30, 40, False)])

    def test_zero_default_disables_random_delay(self):
        rng = FixedRng(.4)
        self.game._action_rng = rng
        self.game._run_steps([{"action": "click", "x": 10, "y": 11}],
                             "pacing", "Slayer Legend")
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(rng.calls, [])
        self.assertEqual(self.backend.click_times, [0.0])

    def test_cancel_during_pacing_prevents_the_click(self):
        self.game._action_rng = FixedRng(.4)
        self.game._click_delay_range = (.2, .5)

        def cancel_during_sleep(seconds):
            self.clock.sleep(seconds)
            self.game.cancel()

        self.game._runner_factory = lambda backend, title, foreground, log: MacroRunner(
            backend, title, foreground, log, sleep=cancel_during_sleep,
            clock=self.clock.clock)
        with self.assertRaises(MacroCancelled):
            self.game._run_steps([{"action": "click", "x": 10, "y": 11}],
                                 "pacing", "Slayer Legend")
        self.assertEqual(self.backend.clicks(), [])
        self.assertIs(self.game._backend, self.backend)

    def test_input_guard_and_other_backend_methods_are_forwarded(self):
        events = []
        self.game._action_rng = FixedRng(.25)
        self.game._click_delay_range = (.25, .25)

        def sleep(seconds):
            events.append(("pause", seconds))
            self.clock.sleep(seconds)

        self.game._runner_factory = lambda backend, title, foreground, log: MacroRunner(
            backend, title, foreground, log, sleep=sleep, clock=self.clock.clock)

        @contextmanager
        def guard():
            events.append("guard-enter")
            yield
            events.append("guard-exit")

        self.game._input_guard = guard
        self.game._settings = replace(self.game._settings, foreground_input=True)
        self.game._run_steps([{"action": "click", "x": 12, "y": 13}],
                             "pacing", "Slayer Legend")
        self.assertEqual(events, ["guard-enter", ("pause", .25), "guard-exit"])
        self.assertEqual(self.backend.clicks(), [(12, 13, True)])
        self.assertIn(("restore",), self.backend.calls)

    def test_backend_and_factory_are_restored_when_factory_or_macro_fails(self):
        original_backend, original_factory = self.game._backend, self.game._runner_factory
        self.game._click_delay_range = (.1, .2)
        self.game._runner_factory = lambda *_args: (_ for _ in ()).throw(RuntimeError("factory failed"))
        failing_factory = self.game._runner_factory
        with self.assertRaisesRegex(RuntimeError, "factory failed"):
            self.game._run_steps([{"action": "click", "x": 1, "y": 2}],
                                 "pacing", "Slayer Legend")
        self.assertIs(self.game._backend, original_backend)
        self.assertIs(self.game._runner_factory, failing_factory)
        self.game._runner_factory = original_factory

        self.backend.click = lambda *_args: (_ for _ in ()).throw(OSError("click failed"))
        with self.assertRaises(MacroError):
            self.game._run_steps([{"action": "click", "x": 1, "y": 2}],
                                 "pacing", "Slayer Legend")
        self.assertIs(self.game._backend, original_backend)
        self.assertIs(self.game._runner_factory, original_factory)

    def test_delay_range_validation_rejects_invalid_bounds(self):
        for value in ((-1, 1), (2, 1), (0, math.inf), (True, 1), (1,), "0.1,0.2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SlayerDailyGame(Settings(window_title="Slayer Legend",
                    macros_dir=Path(self.temp.name)), self.backend,
                    click_delay_range=value)


if __name__ == "__main__":
    unittest.main()
