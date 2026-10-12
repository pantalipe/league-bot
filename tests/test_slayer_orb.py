"""Fixture-backed safety tests for Black Orb navigation and collection."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from test_slayer_attendance import FakeBackend, FakeTime, png_frame, WIDTH, HEIGHT

if la.available():
    from league_bot.game import GameError
    from league_bot.macro import MacroCancelled, MacroError, MacroRunner
    from league_bot.screens import matching_screens
    from league_bot.slayer.home import home_step
    from league_bot.slayer.orb import OrbRunner, OrbState, classify, profiles


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "orb"


def orb_frame(name):
    return png_frame(FIXTURES / f"{name}.png")


class FakeStatus:
    def __init__(self, cycle="daily-1"):
        self.cycle = cycle
        self.records = []

    def cycle_id(self):
        return self.cycle

    def mark_progress(self, *args, **kwargs):
        self.records.append((args, kwargs))

    def snapshot(self):
        return {"tasks": {"macro:blorb": {"progress": self.records[-1][0][1],
                                                 "last_error": ""}}} if self.records else {"tasks": {}}


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class OrbClassificationTests(unittest.TestCase):
    def setUp(self):
        self.data = profiles()

    def test_ready_and_cooldown_fixtures_classify_with_exact_progress(self):
        expected = {
            "free_ready": OrbState("free_ready", 0),
            "ad_ready": OrbState("ad_ready", 1),
            "ad_ready_1": OrbState("ad_ready", 2),
            "ad_cooldown": OrbState("cooldown", 2),
            "exhausted": OrbState("exhausted", 3),
        }
        for name, state in expected.items():
            with self.subTest(name=name):
                self.assertEqual(classify(orb_frame(name), self.data), state)

    def test_panel_and_claimed_fixtures_are_recognized_as_distinct_screens(self):
        screens = self.data["screens"]
        for fixture, screen_name in (("orb_panel", "orb_panel"), ("accessories", "orb_accessories")):
            with self.subTest(fixture=fixture):
                self.assertEqual(matching_screens(orb_frame(fixture), screens), [screen_name])
        # Toast frames are visually useful evidence, but the checked-in screen
        # profile intentionally does not use them as proof of counter progress.
        for fixture in ("free_claimed", "ad_claimed"):
            with self.subTest(fixture=fixture):
                self.assertEqual(matching_screens(orb_frame(fixture), screens), ["orb_panel"])
                with self.assertRaises(MacroError):
                    classify(orb_frame(fixture), self.data)

    def test_unrecognized_or_cost_changed_button_fails_closed(self):
        frame = orb_frame("free_ready")
        # Keep the recognized modal and counter, but invalidate the free-button
        # anchors. The classifier must reject the changed cost/state.
        from league_bot.imaging import Frame
        pixels = bytearray(frame.bgr)
        anchor = self.data["buttons"]["free"][0]
        x, y = round(anchor["x"] * (WIDTH - 1)), round(anchor["y"] * (HEIGHT - 1))
        stride = ((WIDTH * 3 + 3) // 4) * 4
        offset = (HEIGHT - 1 - y) * stride + x * 3
        pixels[offset:offset + 3] = bytes((0, 0, 0))
        changed = Frame(WIDTH, HEIGHT, bytes(pixels))
        with self.assertRaisesRegex(MacroError, "Botao ou custo"):
            classify(changed, self.data)


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class OrbRunnerTests(unittest.TestCase):
    def make_runner(self, *, status=None):
        self.time = FakeTime()
        self.backend = FakeBackend()
        self.runner = OrbRunner(
            self.backend, "Slayer Legend", foreground=True,
            sleep=self.time.sleep, clock=self.time.clock, store=status,
            cycle=status.cycle_id() if status else None,
        )
        return self.runner

    def run_fake_flow(self, runner, states):
        runner._flow = mock.Mock(return_value=runner._backend.hwnd)
        runner._open_modal = mock.Mock(return_value=runner._backend.hwnd)
        runner._state = mock.Mock(side_effect=states)
        # Exercise OrbRunner's branching and click policy while treating
        # generic home/equipment navigation as a deterministic terminal flow.
        with mock.patch.object(MacroRunner, "_do_screen_flow", return_value=runner._backend.hwnd):
            return runner._do_screen_flow({"action": "screen_flow", "black_orb": True}, runner._backend.hwnd)

    def test_free_and_ad_claims_record_only_after_exact_counter_increment(self):
        scenarios = (
            (OrbState("free_ready", 0), OrbState("free_exhausted", 1), 1),
            (OrbState("ad_ready", 1), OrbState("cooldown", 2), 2),
            (OrbState("ad_ready", 2), OrbState("exhausted", 3), 3),
        )
        for before, after, progress in scenarios:
            with self.subTest(before=before):
                status = FakeStatus()
                runner = self.make_runner(status=status)
                self.run_fake_flow(runner, [before, before, after, after])
                self.assertEqual(self.backend.click_log, [(150, 417, False), (217, 656, False)])
                self.assertEqual(runner.outcome.progress, progress)
                self.assertEqual(runner.outcome.acquired, 1)
                self.assertEqual(status.records[-1][0][1], progress)
                self.assertEqual(status.records[-1][1]["source"], "macro")

    def test_counter_without_increment_fails_without_progress_or_retry(self):
        status = FakeStatus()
        runner = self.make_runner(status=status)
        state = OrbState("ad_ready", 1)
        with self.assertRaisesRegex(MacroError, "sem incremento confirmado"):
            self.run_fake_flow(runner, [state, state, state, state])
        self.assertEqual(self.backend.click_log, [(150, 417, False), (217, 656, False)])
        self.assertTrue(status.records)  # the pre-claim counter may seed visual progress
        self.assertTrue(all(record[1]["source"] == "visual" for record in status.records))

    def test_cooldown_and_exhausted_states_never_click_obtain(self):
        for state in (OrbState("cooldown", 2), OrbState("exhausted", 3),
                      OrbState("free_exhausted", 1)):
            with self.subTest(state=state):
                status = FakeStatus()
                runner = self.make_runner(status=status)
                self.run_fake_flow(runner, [state, state])
                self.assertEqual(self.backend.click_log, [(150, 417, False)])
                self.assertEqual(runner.outcome.acquired, 0)
                self.assertEqual(status.records[0][0][1], state.progress)

    def test_unknown_state_stops_before_claim(self):
        status = FakeStatus()
        runner = self.make_runner(status=status)
        with self.assertRaisesRegex(MacroError, "estado desconhecido"):
            self.run_fake_flow(runner, [MacroError("estado desconhecido; nenhuma coleta autorizada")])
        self.assertEqual(self.backend.click_log, [(150, 417, False)])
        self.assertEqual(status.records, [])

    def test_cycle_change_cancels_before_any_claim_input(self):
        status = FakeStatus()
        runner = self.make_runner(status=status)
        status.cycle = "daily-2"
        runner._flow = mock.Mock(return_value=runner._backend.hwnd)
        with mock.patch.object(MacroRunner, "_do_screen_flow", return_value=runner._backend.hwnd):
            with self.assertRaises(MacroCancelled):
                runner._do_screen_flow({"action": "screen_flow", "black_orb": True}, runner._backend.hwnd)
        self.assertEqual(self.backend.click_log, [])
        self.assertEqual(status.records, [])

    def test_home_and_startup_recovery_include_orb_panel_and_modal_close_actions(self):
        home_screens = {screen["name"]: screen for screen in home_step()["screens"]}
        for name, point in (("home_close_orb_modal", (217, 750)),
                            ("home_close_orb_panel", (43, 773))):
            with self.subTest(name=name):
                self.assertEqual(home_screens[name]["click"], {"x": point[0], "y": point[1]})

        settings = SimpleNamespace(
            window_title="Slayer Legend", start_macro="start_game_recognized",
            foreground_input=True,
            macros_dir=ROOT / "league_bot" / "slayer" / "macros",
            data_dir=Path(tempfile.gettempdir()) / "slayer-orb-tests",
            process_names=("SlayerLegend.exe",),
        )
        game = la.HomeSlayerGame(settings, backend=object())
        steps = game.load_macro_steps("start_game_recognized")
        startup = next(step for step in steps if step.get("action") == "screen_flow"
                       and step.get("terminal") == "main")
        by_name = {screen["name"]: screen for screen in startup["screens"]}
        self.assertIn("home_close_orb_modal", by_name)
        self.assertIn("home_close_orb_panel", by_name)


if __name__ == "__main__":
    unittest.main()
