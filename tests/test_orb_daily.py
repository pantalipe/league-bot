"""Daily-runner contract tests for Black Orb outcomes."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la

if la.available():
    from league_bot.slayer.daily import ATTENDANCE_MACRO, HomeDailyRunner
    from league_bot.slayer.orb import OrbOutcome
    from league_bot.slayer.pet import PetOutcome
    from league_bot.slayer.status import BR_TZ, DailyStatusStore
    from league_bot.macro import MacroCancelled, MacroError
    from league_bot.game import GameError
    from league_bot.texts import daily_result


class Entries:
    def __init__(self, macros):
        self.names = list(macros)

    def macros(self):
        return list(self.names)

    def missing(self):
        return []

    def record_run(self, order, when):
        self.order = tuple(order)


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
        self.waits = []
        self.cancelled = False

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
    def __init__(self, clock, handler):
        self.clock, self.handler = clock, handler
        self.calls = []

    def start(self):
        self.calls.append("start")

    def check_attendance(self):
        self.calls.append(ATTENDANCE_MACRO)
        return "claimed"

    def run_macro(self, name):
        self.calls.append(name)
        return self.handler(name)

    def screenshot(self):
        return None


@unittest.skipUnless(la.available(), "league_bot nao encontrado")
class OrbDailyOutcomeTests(unittest.TestCase):
    def make_runner(self, macros, handler, *, seed=None):
        clock = Clock()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = DailyStatusStore(Path(temp.name) / "daily-status.json", now=clock.now)
        if seed:
            seed(store, clock)
        game = Game(clock, handler)
        runner = HomeDailyRunner(game, Entries(macros), status_store=store,
                                 ensure_running=False, now=clock.now)
        runner._cancelled = WaitEvent(clock)
        return runner, store, game, clock

    def test_deferred_orb_is_attempted_once_without_wait_and_other_work_continues(self):
        outcome = OrbOutcome(1, deferred=True, reason="Black Orb: intervalo ativo.", recorded=True)

        def seed(store, clock):
            store.mark_progress("macro:blorb", 1, target=3, label="blorb", source="macro")
            clock.advance(301)

        runner, store, game, _ = self.make_runner(["blorb", "refinamento_skill"], lambda _name: None,
                                                   seed=seed)
        before = store.snapshot()["tasks"]["macro:blorb"]

        def handler(name):
            if name == "blorb":
                store.mark_progress("macro:blorb", outcome.progress, target=3, label="blorb",
                                    source="visual")
                return outcome
            return None

        game.handler = handler
        notices = []
        result = runner.run(on_event=notices.append)
        after = store.snapshot()["tasks"]["macro:blorb"]

        self.assertEqual(result.status, "partial")
        self.assertEqual(game.calls.count("blorb"), 1)
        self.assertEqual(runner._cancelled.waits, [])
        self.assertIn("refinamento_skill", result.done)
        self.assertNotIn("blorb", result.done)
        self.assertIn("blorb", result.pending)
        self.assertIn("Black Orb: intervalo ativo.", notices)
        self.assertEqual(after["progress"], 1)
        self.assertEqual(after.get("last_completed_at"), before.get("last_completed_at"))
        message = daily_result(result)
        self.assertIn("pendencias: blorb", message)
        self.assertIn("Concluidas:", message)

    def test_recorded_absolute_progress_is_not_written_or_incremented_again(self):
        outcomes = iter((OrbOutcome(1, acquired=1, recorded=True),
                         OrbOutcome(2, acquired=1, recorded=True),
                         OrbOutcome(3, acquired=1, recorded=True)))
        calls = []
        runner, store, game, _ = self.make_runner(["blorb"], lambda _name: next(outcomes))
        original = store.mark_progress

        def record(task_id, progress, target=None, **kwargs):
            if task_id == "macro:blorb":
                calls.append((task_id, progress, target, kwargs.get("source")))
            return original(task_id, progress, target, **kwargs)

        store.mark_progress = record

        # Model OrbRunner, which records each confirmed absolute total itself.
        def recorded(name):
            outcome = next(outcomes)
            store.mark_progress("macro:blorb", outcome.progress, 3, label="blorb",
                                source="macro" if outcome.acquired else "visual")
            return outcome

        game.handler = recorded
        result = runner.run()

        self.assertEqual(result.status, "ok")
        self.assertEqual(game.calls.count("blorb"), 3)
        self.assertEqual([item[1] for item in calls], [1, 2, 3])
        task = store.snapshot()["tasks"]["macro:blorb"]
        self.assertEqual((task["progress"], task["target"], task["status"]), (3, 3, "completed"))

    def test_unrecorded_acquisition_persists_reported_absolute_total(self):
        runner, store, game, _ = self.make_runner(
            ["blorb"], lambda _name: OrbOutcome(3, acquired=1, recorded=False))
        result = runner.run()
        task = store.snapshot()["tasks"]["macro:blorb"]

        self.assertEqual(result.status, "ok")
        self.assertEqual(game.calls.count("blorb"), 1)
        self.assertEqual((task["progress"], task["target"], task["status"]), (3, 3, "completed"))
        self.assertEqual(task["source"], "macro")

    def test_exhausted_orb_reconciles_to_complete_without_waiting_or_repeating(self):
        def seed(store, clock):
            store.mark_progress("macro:blorb", 2, target=3, label="blorb", source="macro")
            clock.advance(301)

        def handler(name):
            # The visual runner observed the exhausted counter and reconciled it.
            store.mark_progress("macro:blorb", 3, target=3, label="blorb", source="visual")
            return OrbOutcome(3, deferred=True, reason="Black Orb: limite esgotado.", recorded=True)

        runner, store, game, _ = self.make_runner(["blorb"], handler, seed=seed)
        result = runner.run()
        task = store.snapshot()["tasks"]["macro:blorb"]

        self.assertEqual(result.status, "ok")
        self.assertEqual(game.calls.count("blorb"), 1)
        self.assertEqual(runner._cancelled.waits, [])
        self.assertEqual((task["progress"], task["status"]), (3, "completed"))

    def test_skipped_pet_does_not_change_progress_or_timestamps(self):
        def seed(store, clock):
            store.mark_progress("macro:pet_guild", 0, target=1, label="pet_guild", source="manual")
            clock.advance(12)

        runner, store, game, _ = self.make_runner(
            ["pet_guild", "refinamento_skill"],
            lambda name: PetOutcome(1, True, "Saldo insuficiente") if name == "pet_guild" else None,
            seed=seed)
        before = store.snapshot()["tasks"]["macro:pet_guild"]
        result = runner.run()
        after = store.snapshot()["tasks"]["macro:pet_guild"]

        self.assertEqual(result.status, "partial")
        self.assertEqual(game.calls.count("pet_guild"), 1)
        self.assertIn("refinamento_skill", result.done)
        self.assertIn("pet_guild", result.pending)
        self.assertEqual(after["progress"], before["progress"])
        self.assertEqual(after.get("updated_at"), before.get("updated_at"))
        self.assertEqual(after.get("last_completed_at"), before.get("last_completed_at"))

    def test_known_home_recovery_keeps_macro_pending_without_progress_and_continues(self):
        def handler(name):
            if name == "free_item_shop":
                raise MacroError("screen flow timed out")

        runner, store, game, _ = self.make_runner(["free_item_shop", "refinamento_skill"], handler)
        recoveries = []
        game.recover_home = lambda: recoveries.append("home") or True
        notices = []
        result = runner.run(on_event=notices.append)
        task = store.snapshot()["tasks"]["macro:free_item_shop"]

        self.assertEqual(result.status, "partial")
        self.assertEqual(recoveries, ["home"])
        self.assertIn("refinamento_skill", result.done)
        self.assertIn("free_item_shop", result.pending)
        self.assertEqual((task["progress"], task["status"]), (0, "error"))
        self.assertTrue(any("tela principal recuperada" in note for note in notices))
        message = daily_result(result)
        self.assertIn("pendencias: free_item_shop", message)
        self.assertIn("refinamento_skill", message)

    def test_confirmed_attendance_is_not_opened_again_during_same_cycle(self):
        runner, store, game, _ = self.make_runner(['cobinar_equip'], lambda _name: None)
        store.mark_progress('attendance', 1, source='visual')
        result = runner.run()
        self.assertEqual(result.attendance, 'already_claimed')
        self.assertNotIn('attendance_check', game.calls)
        self.assertIn('cobinar_equip', result.done)

    def test_attendance_is_checked_again_after_cycle_changes(self):
        runner, store, game, clock = self.make_runner(['cobinar_equip'], lambda _name: None)
        store.mark_progress('attendance', 1, source='visual')
        clock.advance(24 * 60 * 60)
        result = runner.run()
        self.assertEqual(result.attendance, 'claimed')
        self.assertIn('attendance_check', game.calls)

    def test_trainer_failure_is_skipped_not_completed_and_notifies_before_continuing(self):
        for failure in (MacroError('training unavailable'), GameError('training unavailable')):
            with self.subTest(failure=type(failure).__name__):
                def handler(name):
                    if name == 'treinador':
                        raise failure
                runner, store, game, _ = self.make_runner(['treinador', 'collect_finished_dailys',
                    'free_wpacs', 'cobinar_equip'], handler)
                game.recover_home = lambda: True
                notices = []
                result = runner.run(on_event=notices.append)
                self.assertEqual(result.status, 'partial')
                self.assertIn('treinador', result.pending)
                self.assertNotIn('treinador', result.done)
                self.assertIn('collect_finished_dailys', result.done)
                self.assertEqual(game.calls.count('treinador'), 1)
                self.assertEqual(store.snapshot()['tasks']['macro:treinador']['progress'], 0)
                self.assertTrue(any('treinador: pulado' in notice for notice in notices))

    def test_unknown_home_recovery_fails_daily_and_stops_following_macros(self):
        def handler(name):
            if name == "free_item_shop":
                raise MacroError("screen unknown")

        runner, _, game, _ = self.make_runner(["free_item_shop", "refinamento_skill"], handler)
        recoveries = []
        game.recover_home = lambda: recoveries.append("home") or False
        result = runner.run()

        self.assertEqual(result.status, "failed")
        self.assertEqual(recoveries, ["home"])
        self.assertEqual(game.calls[-1], "free_item_shop")
        self.assertIn("recuperação falhou", result.error)

    def test_cancellation_does_not_attempt_home_recovery(self):
        def handler(name):
            if name == "free_item_shop":
                raise MacroCancelled("cancelled")

        runner, _, game, _ = self.make_runner(["free_item_shop", "refinamento_skill"], handler)
        recoveries = []
        game.recover_home = lambda: recoveries.append("home") or True
        result = runner.run()

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(recoveries, [])
        self.assertEqual(game.calls[-1], "free_item_shop")

    def test_failed_activation_blocks_bonus_dependent_but_other_work_continues(self):
        def handler(name):
            if name == "ativar_scrolls":
                raise MacroError("bonus screen unknown")

        runner, _, game, _ = self.make_runner(
            ["ativar_scrolls", "montar_besta", "cubo_de_melhora", "refinamento_skill"], handler)
        game.recover_home = lambda: True
        result = runner.run()

        self.assertEqual(result.status, "partial")
        self.assertNotIn("cubo_de_melhora", game.calls)
        self.assertIn("montar_besta", game.calls)
        self.assertIn("refinamento_skill", game.calls)
        self.assertIn("ativar_scrolls", result.pending)
        self.assertIn("cubo_de_melhora", result.pending)

    def test_failed_required_collection_blocks_finished_daily(self):
        def handler(name):
            if name == "free_wpacs":
                raise MacroError("pickup screen unknown")

        runner, _, game, _ = self.make_runner(
            ["free_wpacs", "cobinar_equip", "collect_finished_dailys"], handler)
        game.recover_home = lambda: True
        result = runner.run()

        self.assertEqual(result.status, "partial")
        self.assertNotIn("collect_finished_dailys", game.calls)
        self.assertIn("free_wpacs", result.pending)
        self.assertIn("collect_finished_dailys", result.pending)


if __name__ == "__main__":
    unittest.main()
