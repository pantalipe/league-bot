"""Offline checks for recorded Slayer Goods counter transitions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import slayer_compat as la
from test_slayer_attendance import png_frame

if la.available():
    from league_bot.macro import MacroError
    from league_bot.screens import matching_screens
    from league_bot.slayer.shop import (ShopOutcome, ShopRunner, profiles,
                                        read_counter, read_counters, recovery_screens,
                                        _mask_distance)

FIXTURES = ROOT / 'tests' / 'fixtures' / 'slayer' / 'shop'


@unittest.skipUnless(la.available(), 'Slayer compatibility dependencies unavailable')
class ShopScreenTests(unittest.TestCase):
    def test_shop_summon_and_goods_are_recognized_separately(self):
        screens = recovery_screens()
        self.assertEqual(len(screens), 1)
        self.assertEqual(screens[0]['click'], {'x': 404, 'y': 784})
        summon = png_frame(FIXTURES / 'recording_shop_summon.png')
        self.assertEqual(matching_screens(summon, [profiles()['screens'][0]]), ['shop_open'])
        self.assertEqual(matching_screens(summon, [profiles()['screens'][1]]), [])
        goods = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        self.assertEqual(matching_screens(goods, [profiles()['screens'][1]]), ['shop_goods'])
        toast = png_frame(FIXTURES / 'new_claim_toast.png')
        self.assertEqual(matching_screens(toast, [profiles()['claim_toast']]), ['claim_toast'])
        self.assertEqual(matching_screens(png_frame(FIXTURES / 'stale_main_failure.png'), screens), [])

    def test_recording_fixtures_cover_diamonds_zero_through_ten(self):
        for used in range(11):
            frame = png_frame(FIXTURES / f'recording_diamonds_{used:02}.png')
            self.assertEqual(read_counter(frame, 'diamonds'), (used, 10))
        self.assertEqual({sample['used'] for sample in profiles()['counter_templates']}, set(range(11)))

    def test_emerald_recordings_and_live_failure_crosscheck_shared_counter_font(self):
        for used in (0, 1):
            frame = png_frame(FIXTURES / f'recording_emeralds_{used:02}.png')
            self.assertEqual(read_counter(frame, 'emeralds'), (used, 10))
        self.assertEqual(read_counters(png_frame(FIXTURES / 'goods_after_failure.png')),
                         {'diamonds': (9, 10), 'emeralds': (7, 10)})

    def test_masked_live_emerald_eight_is_distinct_from_seven_and_nine(self):
        frame = png_frame(FIXTURES / 'new_emeralds_08_masked.png')
        self.assertEqual(read_counter(frame, 'emeralds'), (8, 10))
        self.assertEqual(read_counter(png_frame(FIXTURES / 'new_emeralds_07_masked.png'),
                                     'emeralds'), (7, 10))
        data = profiles()
        left, top, right, bottom = data['counter_boxes']['emeralds']
        points = {(x, y) for y in range(top, bottom) for x in range(left, right)
                  if min(frame.pixel(x, y)) >= 140 and max(frame.pixel(x, y))-min(frame.pixel(x, y)) <= 65}
        x0, y0 = min(x for x, _ in points), min(y for _, y in points)
        x1, y1 = max(x for x, _ in points), max(y for _, y in points)
        observed = [''.join('1' if (x, y) in points else '0' for x in range(x0, x1+1))
                    for y in range(y0, y1+1)]
        templates = {sample['used']: sample['mask'] for sample in data['counter_templates']}
        self.assertEqual(_mask_distance(observed, templates[8]), 0)
        self.assertGreater(_mask_distance(observed, templates[7]), 0)
        self.assertGreater(_mask_distance(observed, templates[9]), 0)

    def test_single_claim_requires_exact_increment_and_preserves_other_counter(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        after = png_frame(FIXTURES / 'recording_claim_after_d1_e0.png')
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend', sleep=lambda _seconds: None,
                            clock=lambda: 1.0)
        runner._observe = mock.Mock(return_value=(read_counters(before), before))
        runner._ad_ready = mock.Mock(return_value=True)
        runner._wait_for_increment = mock.Mock(return_value=(read_counters(after), after))
        hwnd, counts, _ = runner._claim_once(7, 'diamonds', read_counters(before), before)
        self.assertEqual(hwnd, 7)
        self.assertEqual(counts, {'diamonds': (1, 10), 'emeralds': (0, 10)})
        backend.click.assert_called_once_with(7, 343, 375, False)
        runner._wait_for_increment.assert_called_once_with(7, read_counters(before), 'diamonds', timeout=120)

    def _claim_with_frames(self, frames, timeout=120):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.side_effect = frames
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        runner = ShopRunner(backend, 'Slayer Legend', sleep=sleep, clock=lambda: now[0])
        runner._observe = mock.Mock(return_value=(read_counters(before), before))
        runner._ad_ready = mock.Mock(return_value=True)
        result = runner._claim_once(7, 'diamonds', read_counters(before), before, timeout=timeout)
        return runner, backend, result

    def test_claim_waits_through_old_counter_until_exact_increment_is_stable(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        after = png_frame(FIXTURES / 'recording_claim_after_d1_e0.png')
        runner, backend, (_, counts, frame) = self._claim_with_frames(
            [before, before, after, after])
        self.assertEqual(counts, {'diamonds': (1, 10), 'emeralds': (0, 10)})
        self.assertIs(frame, after)
        backend.click.assert_called_once_with(7, 343, 375, False)

    def test_claim_rejects_wrong_increment_without_retry(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        wrong = png_frame(FIXTURES / 'new_goods_d2_e0.png')
        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.return_value = wrong
        runner = ShopRunner(backend, 'Slayer Legend', sleep=lambda _seconds: None,
                            clock=lambda: 1.0)
        runner._observe = mock.Mock(return_value=(read_counters(before), before))
        runner._ad_ready = mock.Mock(return_value=True)
        with self.assertRaises(MacroError):
            runner._claim_once(7, 'diamonds', read_counters(before), before)
        backend.click.assert_called_once_with(7, 343, 375, False)

    def test_claim_timeout_after_click_does_not_retry(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.return_value = before
        now = [0.0]
        runner = ShopRunner(backend, 'Slayer Legend',
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
        runner._observe = mock.Mock(return_value=(read_counters(before), before))
        runner._ad_ready = mock.Mock(return_value=True)
        with self.assertRaisesRegex(MacroError, 'incremento do anuncio nao confirmado'):
            runner._claim_once(7, 'diamonds', read_counters(before), before, timeout=.6)
        backend.click.assert_called_once_with(7, 343, 375, False)

    def test_observe_ignores_transient_claim_toast_and_waits_for_clean_counter(self):
        toast = png_frame(FIXTURES / 'new_claim_toast.png')
        clean = png_frame(FIXTURES / 'new_goods_d10_e9.png')
        # The toast overlaps the glyph box and can make the raw reader see E0.
        self.assertEqual(read_counter(toast, 'emeralds'), (0, 10))
        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.side_effect = [toast, clean, clean]
        now = [0.0]
        runner = ShopRunner(backend, 'Slayer Legend',
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
        counts, frame = runner._observe(7, timeout=2)
        self.assertEqual(counts, {'diamonds': (10, 10), 'emeralds': (9, 10)})
        self.assertIs(frame, clean)

    def test_increment_wait_ignores_toast_then_requires_two_clean_exact_frames(self):
        toast = png_frame(FIXTURES / 'new_claim_toast.png')
        clean = png_frame(FIXTURES / 'new_goods_d10_e9.png')
        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.side_effect = [toast, clean, clean]
        now = [0.0]
        runner = ShopRunner(backend, 'Slayer Legend',
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
        before = {'diamonds': (10, 10), 'emeralds': (8, 10)}
        after, frame = runner._wait_for_increment(7, before, 'emeralds', timeout=2)
        self.assertEqual(after, {'diamonds': (10, 10), 'emeralds': (9, 10)})
        self.assertIs(frame, clean)

    def test_emerald_ad_uses_its_own_free_control_and_confirms_other_counter_unchanged(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        after = png_frame(FIXTURES / 'recording_claim_after_d0_e1.png')
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend', sleep=lambda _seconds: None,
                            clock=lambda: 1.0)
        runner._observe = mock.Mock(return_value=(read_counters(before), before))
        runner._ad_ready = mock.Mock(return_value=True)
        runner._wait_for_increment = mock.Mock(return_value=(read_counters(after), after))
        _, counts, _ = runner._claim_once(7, 'emeralds', read_counters(before), before)
        self.assertEqual(counts, {'diamonds': (0, 10), 'emeralds': (1, 10)})
        backend.click.assert_called_once_with(7, 353, 446, False)

    def test_missing_or_wrong_increment_causes_no_retry_and_never_uses_paid_offer(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        for name in ('recording_claim_after_d2_e0.png',):
            after = png_frame(FIXTURES / name)
            backend = mock.Mock()
            runner = ShopRunner(backend, 'Slayer Legend', sleep=lambda _seconds: None,
                                clock=lambda: 1.0)
            runner._observe = mock.Mock(return_value=(read_counters(before), before))
            runner._ad_ready = mock.Mock(return_value=True)
            runner._wait_for_increment = mock.Mock(side_effect=MacroError('wrong increment'))
            with self.assertRaises(MacroError):
                runner._claim_once(7, 'diamonds', read_counters(before), before)
            backend.click.assert_called_once_with(7, 343, 375, False)
            clicked = [(call.args[1], call.args[2]) for call in backend.click.call_args_list]
            self.assertNotIn((343, 518), clicked)

    def test_deferred_partial_progress_is_skipped_but_exhausted_shop_is_complete(self):
        self.assertTrue(ShopOutcome(progress=16, acquired=0, deferred=True).skipped)
        self.assertFalse(ShopOutcome(progress=20, acquired=0, deferred=False).skipped)

    def test_live_goods_layout_reads_both_ten_of_ten_counters(self):
        frame = png_frame(FIXTURES / 'new_goods_both_10_masked.png')
        self.assertEqual(read_counters(frame),
                         {'diamonds': (10, 10), 'emeralds': (10, 10)})

    def test_conflicting_counter_layouts_fail_closed(self):
        frame = png_frame(FIXTURES / 'ambiguous_goods_counter_layouts.png')
        with self.assertRaises(MacroError):
            read_counters(frame)

    def test_unreadable_live_counter_fails_closed(self):
        frame = png_frame(FIXTURES / 'unknown_goods_counters.png')
        with self.assertRaises(MacroError):
            read_counters(frame)

    def test_unrecognized_screen_has_no_readable_counter(self):
        with self.assertRaises(MacroError):
            read_counters(png_frame(FIXTURES / 'stale_main_failure.png'))

    def test_collection_flow_uses_calibrated_templates_until_both_limits(self):
        runner = ShopRunner(mock.Mock(), 'Slayer Legend')
        initial = {'diamonds': (9, 10), 'emeralds': (9, 10)}
        middle = {'diamonds': (10, 10), 'emeralds': (9, 10)}
        final = {'diamonds': (10, 10), 'emeralds': (10, 10)}
        runner._ensure_goods = mock.Mock(return_value=7)
        runner._observe = mock.Mock(return_value=(initial, None))
        runner._ad_ready = mock.Mock(return_value=True)
        runner._claim_once = mock.Mock(side_effect=[(7, middle, None), (7, final, None)])
        with mock.patch('league_bot.macro.MacroRunner._do_screen_flow', return_value=7):
            runner._do_screen_flow({'free_item_shop': True}, 7)
        self.assertEqual(runner.outcome.progress, 20)
        self.assertEqual(runner.outcome.acquired, 2)
        self.assertFalse(runner.outcome.skipped)
        self.assertEqual([call.args[1] for call in runner._claim_once.call_args_list],
                         ['diamonds', 'emeralds'])

    def test_game_entry_constructs_valid_steps_and_restores_runner_factory(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from league_bot.macro import MacroRunner, validate_steps
        from league_bot.slayer.shop import run_shop
        backend=mock.Mock()
        previous=lambda backend,title,foreground,log: MacroRunner(backend,title,foreground,log)
        game=SimpleNamespace(_status_store=None,_runner_factory=previous,
            _exclusive=nullcontext,_title=lambda:'Slayer Legend',final_steps=lambda:[])
        def execute(steps,name,title):
            validate_steps(steps)
            runner=game._runner_factory(backend,title,False,lambda _message:None)
            runner.outcome=ShopOutcome(20)
        game._run_steps=execute
        result=run_shop(game)
        self.assertEqual(result.progress,20)
        self.assertIs(game._runner_factory,previous)


if __name__ == '__main__':
    unittest.main()
