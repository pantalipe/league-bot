"""Scheduling tests for the named daily plan."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la

if la.available():
    from league_bot.slayer.plan import DEFAULT_MACROS, ordered_macros
    from league_bot.slayer.status import BR_TZ, DailyStatusStore
    from league_bot.slayer.daily import HomeDailyRunner, ATTENDANCE_MACRO
    from league_bot.daily import DailyError


class Entries:
    def __init__(self, macros):
        self.names = list(macros)
        self.recorded = None

    def macros(self):
        return list(self.names)

    def missing(self):
        return []

    def last_order(self):
        return []

    def record_run(self, order, when):
        self.recorded = tuple(order)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 11, 3, 0, tzinfo=BR_TZ)

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class WaitEvent:
    def __init__(self, clock):
        self.clock = clock
        self.cancelled = False
        self.waits = []

    def is_set(self):
        return self.cancelled

    def set(self):
        self.cancelled = True

    def clear(self):
        self.cancelled = False

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.advance(seconds)
        return self.cancelled


class Game:
    def __init__(self, clock=None, *, rollover_macro=None):
        self.calls = []
        self.runs = []
        self.clock = clock
        self.rollover_macro = rollover_macro
        self.runner = None
        self.durations = {}

    def start(self):
        self.calls.append("start")

    def check_attendance(self):
        self.calls.append(ATTENDANCE_MACRO)
        return "claimed"

    def run_macro(self, name):
        self.calls.append(name)
        self.runs.append((name, self.clock.now() if self.clock else None))
        if self.clock and self.durations.get(name):
            self.clock.advance(self.durations[name])
        if name == self.rollover_macro:
            self.clock.advance(23 * 3600)

    def screenshot(self):
        return None

    def cancel(self):
        if self.runner:
            self.runner._cancelled.set()


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class DailyPlanTests(unittest.TestCase):
    def make_runner(self, macros, *, clock=None, game=None):
        clock = clock or Clock()
        game = game or Game(clock)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = DailyStatusStore(Path(temp.name) / "daily-status.json", now=clock.now)
        runner = HomeDailyRunner(game, Entries(macros), status_store=store,
                                 ensure_running=False, now=clock.now)
        runner._cancelled = WaitEvent(clock)
        game.runner = runner
        return runner, store, game, clock

    def test_default_plan_excludes_diamond_pet_and_finishes_with_daily_collection(self):
        self.assertEqual(len(DEFAULT_MACROS), 18)
        self.assertIn("pet_guild", DEFAULT_MACROS)
        ordered = ordered_macros(DEFAULT_MACROS)
        self.assertLess(ordered.index("ativar_scrolls"), ordered.index("cubo_de_melhora"))
        self.assertLess(ordered.index("montar_besta"), ordered.index("cave_treinoxp"))
        self.assertEqual(ordered[-1], "collect_finished_dailys")

    def test_bonus_and_finished_daily_dependencies_rejected_before_actions(self):
        runner, _, game, _ = self.make_runner(["cubo_de_melhora"])
        with self.assertRaises(DailyError):
            runner.run()
        self.assertEqual(game.calls, [])
        runner, _, game, _ = self.make_runner(["collect_finished_dailys", "free_wpacs"])
        with self.assertRaises(DailyError):
            runner.run()
        self.assertEqual(game.calls, [])

    def test_repeated_macro_waits_between_three_successful_runs(self):
        runner, store, game, _ = self.make_runner(["blorb"])
        result = runner.run()
        self.assertEqual(result.status, "ok")
        self.assertEqual(game.calls.count("blorb"), 3)
        self.assertEqual(runner._cancelled.waits, [300, 300])
        task = store.snapshot()["tasks"]["macro:blorb"]
        self.assertEqual((task["progress"], task["target"], task["status"]), (3, 3, "completed"))

    def test_full_daily_interleaves_cooldowns_announces_bonuses_and_finishes_last(self):
        runner, _, game, _ = self.make_runner(DEFAULT_MACROS)
        game.durations["ativar_scrolls"] = 120
        notices = []
        result = runner.run(on_event=notices.append)
        self.assertEqual(result.status, "ok")
        macro_calls = [name for name in game.calls if name not in {"start", ATTENDANCE_MACRO}]
        self.assertEqual(macro_calls[-1], "collect_finished_dailys")
        self.assertEqual(macro_calls.count("blorb"), 3)
        self.assertEqual(macro_calls.count("free_wpacs"), 3)
        names = [name for name, _when in game.runs]
        self.assertLess(names.index("ativar_scrolls"), names.index("cubo_de_melhora"))
        blorb_times = [when for name, when in game.runs if name == "blorb"]
        wpacs_times = [when for name, when in game.runs if name == "free_wpacs"]
        self.assertTrue(all((b - a).total_seconds() >= 300 for a, b in zip(blorb_times, blorb_times[1:])))
        self.assertTrue(all((b - a).total_seconds() >= 600 for a, b in zip(wpacs_times, wpacs_times[1:])))
        self.assertIn("Ativando os bônus diários: scrolls.", notices)
        self.assertIn("Ativando os bônus diários: montaria.", notices)
        self.assertLess(macro_calls.index("ativar_scrolls"), macro_calls.index("blorb", 1))

    def test_completed_repeat_is_skipped(self):
        runner, store, game, _ = self.make_runner(["blorb"])
        store.mark_progress("macro:blorb", 3, target=3, label="blorb", source="macro")
        result = runner.run()
        self.assertEqual(result.status, "ok")
        self.assertNotIn("blorb", game.calls)

    def test_wait_is_cancellable_and_next_run_resumes_saved_count(self):
        runner, store, game, clock = self.make_runner(["blorb"])
        event = runner._cancelled
        original_wait = event.wait

        def cancel_wait(seconds):
            event.waits.append(seconds)
            event.set()
            return True

        event.wait = cancel_wait
        first = runner.run()
        self.assertEqual(first.status, "cancelled")
        self.assertEqual(store.snapshot()["tasks"]["macro:blorb"]["progress"], 1)
        clock.advance(301)
        event.wait = original_wait
        second = runner.run()
        self.assertEqual(second.status, "ok")
        self.assertEqual(game.calls.count("blorb"), 3)

    def test_cycle_change_during_macro_aborts_before_next_action(self):
        clock = Clock()
        game = Game(clock, rollover_macro="ativar_scrolls")
        runner, store, _, _ = self.make_runner(["ativar_scrolls", "montar_besta", "cubo_de_melhora"],
                                                clock=clock, game=game)
        result = runner.run()
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(game.calls, [ATTENDANCE_MACRO, "ativar_scrolls"])
        self.assertNotIn("macro:ativar_scrolls", store.snapshot()["tasks"])

    def test_pet_insufficient_balance_keeps_daily_running(self):
        from league_bot.slayer.pet import PetOutcome
        runner, store, game, _ = self.make_runner(["pet_guild", "refinamento_skill"])
        original = game.run_macro
        def run(name):
            original(name)
            if name == "pet_guild":
                return PetOutcome(1,True,"Saldo insuficiente")
        game.run_macro = run
        notices = []
        result = runner.run(on_event=notices.append)
        self.assertEqual(result.status,"ok")
        self.assertIn("refinamento_skill",result.done)
        self.assertNotIn("pet_guild",result.done)
        self.assertIn("Saldo insuficiente",notices)
        self.assertEqual(store.snapshot()["tasks"]["macro:pet_guild"]["progress"],0)


if __name__ == "__main__":
    unittest.main()
