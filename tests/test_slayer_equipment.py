"""Regression coverage for the 2026-10-12 interrupted soul-harvest daily."""
import copy
import unittest
from pathlib import Path

from league_bot.config import Settings
from league_bot.imaging import solid_frame
from league_bot.macro import MacroRunner, MacroError, MacroCancelled, load_macro, validate_steps
from league_bot.screens import matching_screens
from league_bot.slayer.equipment import (
    equipment_entry_step, equipment_weapon_step, prepare_soul_harvest,
)
from league_bot.slayer.home import home_step
from league_bot.slayer.game import SlayerDailyGame
from test_slayer_attendance import FakeBackend, FakeTime, png_frame

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests/fixtures/slayer/home'


def frame(name):
    return png_frame(FIXTURES / (name + '.png'))


class EquipmentRecoveryTests(unittest.TestCase):
    def runner(self, frames):
        self.backend = FakeBackend(frames)
        self.time = FakeTime()
        return MacroRunner(self.backend, 'Slayer Legend', False,
                           sleep=self.time.sleep, clock=self.time.clock)

    def test_real_failure_frames_match_the_expected_states(self):
        self.assertEqual(matching_screens(frame('equipment_accessories'), home_step()['screens']),
                         ['home_close_equipment'])
        self.assertEqual(matching_screens(frame('failed_soul_main'), home_step()['screens']), ['main'])
        for path in FIXTURES.glob('*.png'):
            matches = matching_screens(png_frame(path), equipment_entry_step()['screens'])
            if path.stem in {'equipment_accessories', 'equipment_weapon'}:
                self.assertEqual(matches, ['equipment_open'])
            else:
                self.assertNotIn('equipment_open', matches)

    def test_recovery_closes_accessories_then_confirms_main(self):
        runner = self.runner([frame('equipment_accessories')]*2 + [frame('main')]*2)
        runner.run([home_step()])
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_startup_recovers_equipment_before_minimizing(self):
        game = SlayerDailyGame(Settings(), object())
        flow = next(s for s in game.load_macro_steps('start_game_recognized') if s['action'] == 'screen_flow')
        runner = self.runner([frame('equipment_accessories')]*2 + [frame('main')]*2)
        runner.run([flow])
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_missed_entry_click_retries_only_recognized_navigation(self):
        runner = self.runner([frame('failed_soul_main')]*16 + [frame('equipment_accessories')]*2)
        runner.run([equipment_entry_step()])
        self.assertEqual(self.backend.click_log, [(184, 784, False)]*2)
        self.assertGreaterEqual(self.time.now, 3)

    def test_accessories_and_weapon_start_states_both_finish_on_weapon(self):
        cases = (
            ([frame('equipment_accessories')]*4 + [frame('equipment_weapon')]*2,
             [(65, 421, False)]),
            ([frame('equipment_weapon')]*4, []),
        )
        for frames, expected_clicks in cases:
            with self.subTest(expected_clicks=expected_clicks):
                runner = self.runner(frames)
                runner.run([equipment_entry_step(), equipment_weapon_step()])
                self.assertEqual(self.backend.click_log, expected_clicks)

    def test_unrecognized_equipment_content_times_out_without_subtab_click(self):
        runner = self.runner([frame('main')])
        with self.assertRaisesRegex(MacroError, 'timed out.*unknown'):
            runner.run([equipment_weapon_step()])
        self.assertEqual(self.backend.click_log, [])

    def test_persistent_main_stops_after_two_clicks(self):
        runner = self.runner([frame('failed_soul_main')])
        with self.assertRaisesRegex(MacroError, 'click limit'):
            runner.run([equipment_entry_step()])
        self.assertEqual(self.backend.click_log, [(184, 784, False)]*2)

    def test_unknown_frames_never_retry_a_navigation_click(self):
        runner = self.runner([frame('main')]*2 + [solid_frame(434, 810, (0, 0, 0))]*60)
        with self.assertRaisesRegex(MacroError, 'timed out.*unknown'):
            runner.run([equipment_entry_step()])
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_cancellation_stops_before_retry(self):
        runner = self.runner([frame('main')])
        capture = self.backend.capture
        def cancel(hwnd):
            if self.backend.click_log:
                runner.cancel()
            return capture(hwnd)
        self.backend.capture = cancel
        with self.assertRaises(MacroCancelled):
            runner.run([equipment_entry_step()])
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_default_flow_does_not_retry_a_persistent_screen(self):
        step = equipment_entry_step()
        del step['screens'][0]['retry_after_seconds']
        runner = self.runner([frame('main')])
        with self.assertRaisesRegex(MacroError, 'timed out'):
            runner.run([step])
        self.assertEqual(self.backend.click_log, [(184, 784, False)])

    def test_recorded_reward_guards_are_preserved_and_custom_entries_untouched(self):
        original = load_macro(ROOT / 'league_bot/slayer/macros/colheita_arma_alma.json')
        prepared = prepare_soul_harvest(original)
        self.assertEqual(prepared[3:], original[6:])
        self.assertEqual(prepared[1]['action'], 'screen_flow')
        self.assertEqual(prepared[2]['terminal'], 'equipment_weapon')
        game = SlayerDailyGame(Settings(), object())
        integrated = game.load_macro_steps('colheita_arma_alma')
        self.assertIn('equipment_open', [s.get('terminal') for s in integrated])
        self.assertIn({'action':'click','x':65,'y':421}, integrated)
        self.assertNotIn('wait_for_pixel', [s['action'] for s in integrated])
        validate_steps(integrated)
        custom = copy.deepcopy(original)
        custom[2]['x'] = '55%'
        self.assertEqual(prepare_soul_harvest(custom), custom)
        for index, key, value in (
            (4, 'x', '16%'), (4, 'color', [136, 130, 128]),
            (5, 'x', '16%'), (5, 'action', 'wait'),
        ):
            with self.subTest(index=index, key=key):
                variant = copy.deepcopy(original)
                variant[index][key] = value
                self.assertEqual(prepare_soul_harvest(variant), variant)
        self.assertEqual(original[2]['x'], '42.51%')

    def test_retry_configuration_is_validated_before_input(self):
        for value in (0, -1, float('nan'), True, '3'):
            step = equipment_entry_step()
            step['screens'][0]['retry_after_seconds'] = value
            with self.assertRaisesRegex(MacroError, 'retry_after_seconds'):
                validate_steps([step])


if __name__ == '__main__':
    unittest.main()
