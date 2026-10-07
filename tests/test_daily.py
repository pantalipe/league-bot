import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from league_bot.config import Settings
from league_bot.daily import DailyBusy, DailyError, DailyList, DailyRunner, build_runner, shuffled_order
from league_bot.game import GameBusy, GameError
from league_bot.imaging import solid_frame
from league_bot.library import MacroLibrary
from league_bot.macro import MacroError

STEPS = [{"action": "wait"}]
NOW = datetime(2026, 10, 6, 21, 0, 0)


class FakeGame:
    """Just enough of SlayerGame for the runner; records what it was asked to do."""

    def __init__(self, library):
        self.library = library
        self.events = []
        self.fail_on = None
        self.start_error = None
        self.screenshot_error = None
        self.on_run = None
        self.frame = solid_frame(4, 4, (1, 2, 3))

    def start(self):
        self.events.append("start")
        if self.start_error:
            raise self.start_error
        return "iniciado"

    def run_macro(self, name):
        self.events.append("run:" + name)
        if self.on_run:
            self.on_run(name)
        if self.fail_on == name:
            raise MacroError("passo 3 falhou")
        return "ok"

    def screenshot(self):
        if self.screenshot_error:
            raise self.screenshot_error
        return self.frame

    def cancel(self):
        self.events.append("cancel")
        return True


class StubRng:
    """A 'random' generator whose shuffle never changes anything."""

    def shuffle(self, items):
        pass


class OrderTests(unittest.TestCase):
    def test_result_is_always_a_permutation(self):
        macros = ["a", "b", "c", "d"]
        for seed in range(50):
            order = shuffled_order(macros, [], random.Random(seed))
            self.assertEqual(sorted(order), macros)

    def test_never_repeats_the_last_order_when_another_exists(self):
        for seed in range(200):
            self.assertNotEqual(shuffled_order(["a", "b"], ["a", "b"], random.Random(seed)), ["a", "b"])
            self.assertNotEqual(shuffled_order(["a", "b", "c"], ["c", "a", "b"], random.Random(seed)), ["c", "a", "b"])

    def test_guarantee_holds_even_when_shuffling_keeps_failing(self):
        self.assertEqual(shuffled_order(["a", "b", "c"], ["a", "b", "c"], StubRng()), ["b", "c", "a"])

    def test_one_macro_has_only_one_order_and_inputs_are_not_mutated(self):
        self.assertEqual(shuffled_order(["a"], ["a"], random.Random(1)), ["a"])
        macros = ["a", "b", "c"]
        shuffled_order(macros, [], random.Random(1))
        self.assertEqual(macros, ["a", "b", "c"])

    def test_a_changed_list_is_not_compared_with_stale_history(self):
        self.assertEqual(sorted(shuffled_order(["a", "b"], ["x", "y", "z"], random.Random(3))), ["a", "b"])


class DailyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.library = MacroLibrary(self.root / "macros")
        for name in ("a", "b", "c"):
            self.library.save(name, STEPS)
        self.entries = DailyList(self.root / "state" / "daily.json", self.library)


class DailyListTests(DailyCase):
    def test_add_remove_and_persistence(self):
        self.assertEqual(self.entries.macros(), [])
        self.entries.add("b")
        self.entries.add("a")
        self.assertEqual(self.entries.macros(), ["b", "a"])  # insertion order is kept
        reopened = DailyList(self.root / "state" / "daily.json", self.library)
        self.assertEqual(reopened.macros(), ["b", "a"])
        self.entries.remove("b")
        self.assertEqual(reopened.macros(), ["a"])
        self.assertEqual(list((self.root / "state").glob("*.tmp")), [])

    def test_refuses_duplicates_unknown_invalid_and_absent_names(self):
        self.entries.add("a")
        with self.assertRaisesRegex(DailyError, "ja esta"):
            self.entries.add("a")
        with self.assertRaisesRegex(DailyError, "nao existe.*a, b, c"):
            self.entries.add("ghost")
        with self.assertRaisesRegex(DailyError, "invalido"):
            self.entries.add("../evil")
        with self.assertRaisesRegex(DailyError, "nao esta"):
            self.entries.remove("b")

    def test_missing_reports_macros_deleted_after_they_were_added(self):
        self.entries.add("a")
        self.entries.add("b")
        self.library.delete("b")
        self.assertEqual(self.entries.missing(), ["b"])

    def test_record_run_keeps_the_list_and_remembers_the_order(self):
        self.entries.add("a")
        self.entries.record_run(["b", "a"], NOW)
        self.assertEqual((self.entries.macros(), self.entries.last_order()), (["a"], ["b", "a"]))
        self.assertEqual(self.entries.last_run(), "2026-10-06T21:00:00")

    def test_unusable_file_is_reported_not_silently_replaced(self):
        path = self.root / "state" / "daily.json"
        path.parent.mkdir()
        path.write_text("{oops", encoding="utf-8")
        with self.assertRaisesRegex(DailyError, "invalido"):
            self.entries.macros()
        with self.assertRaises(DailyError):
            self.entries.add("a")
        self.assertEqual(path.read_text(encoding="utf-8"), "{oops")


class RunnerTests(DailyCase):
    def setUp(self):
        super().setUp()
        for name in ("a", "b", "c"):
            self.entries.add(name)
        self.game = FakeGame(self.library)
        self.runner = DailyRunner(self.game, self.entries, rng=random.Random(7), now=lambda: NOW)

    def macro_runs(self):
        return [e[4:] for e in self.game.events if e.startswith("run:")]

    def test_runs_every_macro_once_in_a_random_order_after_starting_the_game(self):
        result = self.runner.run()
        self.assertEqual((result.status, result.error), ("ok", ""))
        self.assertEqual(self.game.events[0], "start")
        self.assertEqual(sorted(self.macro_runs()), ["a", "b", "c"])
        self.assertEqual(list(result.order), self.macro_runs())
        self.assertEqual(result.done, result.order)
        self.assertEqual(result.frame, self.game.frame)
        self.assertEqual(self.entries.last_order(), list(result.order))

    def test_reports_the_order_before_running_anything(self):
        seen = []
        self.game.on_run = lambda name: seen.append(("run", name))
        result = self.runner.run(on_start=lambda order: seen.append(("order", order)))
        self.assertEqual(seen[0], ("order", result.order))

    def test_consecutive_runs_use_different_orders(self):
        previous = None
        for _ in range(12):
            self.game.events.clear()
            order = self.runner.run().order
            self.assertNotEqual(order, previous)
            previous = order

    def test_does_not_start_the_game_when_told_not_to(self):
        runner = DailyRunner(self.game, self.entries, rng=random.Random(1), ensure_running=False)
        runner.run()
        self.assertNotIn("start", self.game.events)

    def test_a_failing_macro_stops_the_daily_and_reports_progress(self):
        runner = DailyRunner(self.game, self.entries, rng=random.Random(1))
        order = shuffled_order(["a", "b", "c"], [], random.Random(1))
        self.game.fail_on = order[1]
        result = runner.run()
        self.assertEqual(result.status, "failed")
        self.assertIn("passo 3 falhou", result.error)
        self.assertEqual(result.done, (order[0],))
        self.assertEqual(self.macro_runs(), order[:2])  # nothing ran after the failure

    def test_failing_to_start_the_game_runs_nothing(self):
        self.game.start_error = GameError("janela nao encontrada")
        result = self.runner.run()
        self.assertEqual((result.status, result.done), ("failed", ()))
        self.assertIn("janela", result.error)
        self.assertEqual(self.macro_runs(), [])

    def test_cancel_stops_before_the_next_macro_and_aborts_the_current_one(self):
        self.game.on_run = lambda name: self.runner.cancel()
        result = self.runner.run()
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(len(result.done), 1)
        self.assertEqual(len(self.macro_runs()), 1)
        self.assertIn("cancel", self.game.events)  # the macro in progress was told to stop

    def test_cancel_when_idle_does_nothing(self):
        self.assertFalse(self.runner.cancel())
        self.assertNotIn("cancel", self.game.events)

    def test_a_second_daily_is_refused_while_one_runs(self):
        seen = {}

        def during(name):
            seen["running"] = self.runner.running
            try:
                self.runner.run()
            except DailyBusy as exc:
                seen["busy"] = exc

        self.game.on_run = during
        self.runner.run()
        self.assertTrue(seen["running"])
        self.assertIsInstance(seen["busy"], DailyBusy)
        self.assertFalse(self.runner.running)
        self.runner.run()  # and it is free again afterwards

    def test_a_missing_screenshot_does_not_spoil_a_finished_daily(self):
        self.game.screenshot_error = GameError("sem janela")
        result = self.runner.run()
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.frame)

    def test_busy_game_is_reported_as_a_failure_with_the_reason(self):
        self.game.start_error = GameBusy("Ja existe uma operacao em andamento")
        result = self.runner.run()
        self.assertEqual(result.status, "failed")
        self.assertIn("operacao em andamento", result.error)

    def test_refuses_an_empty_daily_and_one_with_vanished_macros(self):
        empty = DailyList(self.root / "other.json", self.library)
        with self.assertRaisesRegex(DailyError, "vazia"):
            DailyRunner(self.game, empty).run()
        self.library.delete("c")
        with self.assertRaisesRegex(DailyError, "nao existem mais: c"):
            self.runner.run()
        self.assertEqual(self.game.events, [])  # nothing was started

    def test_list_management_goes_through_the_runner(self):
        self.runner.remove("a")
        self.assertEqual(self.runner.macros(), ["b", "c"])
        self.runner.add("a")
        self.assertEqual(self.runner.macros(), ["b", "c", "a"])
        self.assertEqual(self.runner.missing(), [])


class BuildTests(DailyCase):
    def test_build_runner_keeps_the_list_in_the_data_dir(self):
        settings = Settings(data_dir=self.root / "state", macros_dir=self.root / "macros")
        runner = build_runner(FakeGame(self.library), settings)
        runner.add("a")
        self.assertTrue((self.root / "state" / "daily.json").is_file())


if __name__ == "__main__":
    unittest.main()
