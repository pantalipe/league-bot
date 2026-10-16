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
    from league_bot.macro import MacroCancelled, MacroError
    from league_bot.screens import matching_screens
    from league_bot.slayer.shop import (ShopOutcome, ShopRunner, profiles,
                                        read_counter, read_counters, recovery_screens,
                                        _mask_distance)

FIXTURES = ROOT / 'tests' / 'fixtures' / 'slayer' / 'shop'


@unittest.skipUnless(la.available(), 'Slayer compatibility dependencies unavailable')
class ShopScreenTests(unittest.TestCase):
    def test_current_vertical_free_rows_use_existing_video_controls(self):
        frame=png_frame(FIXTURES/'goods-current-0of10.png')
        self.assertEqual(read_counters(frame),{'diamonds':(0,10),'emeralds':(0,10)})
        runner=ShopRunner(object(),'Slayer Legend')
        self.assertEqual(runner._ad_button(frame,'diamonds')['click'],{'x':356,'y':395})
        self.assertEqual(runner._ad_button(frame,'emeralds')['click'],{'x':356,'y':467})
        after=png_frame(FIXTURES/'goods-current-diamonds-10.png')
        self.assertEqual(read_counters(after),{'diamonds':(10,10),'emeralds':(0,10)})

    def test_position_recovery_swipes_only_until_counters_return(self):
        from league_bot.imaging import Frame
        frame=png_frame(FIXTURES/'recording_claim_before_d0_e0.png')
        pixels=bytearray(frame.bgr)
        data=profiles()
        for kind,box in data['counter_boxes'].items():
            for left,top,right,bottom in data.get('counter_box_variants',{}).get(kind,[box]):
                for y in range(top,bottom):
                    start=(809-y)*frame.row_size+left*3
                    pixels[start:start+(right-left)*3]=bytes((right-left)*3)
        unknown=Frame(434,810,bytes(pixels))
        backend=mock.Mock();backend.client_size.return_value=(434,810)
        backend.capture.side_effect=[unknown,frame]
        runner=ShopRunner(backend,'Slayer Legend');runner._pause=mock.Mock()
        self.assertEqual(runner._position_goods(7),7)
        backend.drag.assert_called_once_with(7,220,340,220,650)
        backend.click.assert_not_called()
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

    def test_live_goods_zero_counters_are_distinctly_calibrated(self):
        frame = png_frame(FIXTURES / 'new_goods_d0_e0_live_masked.png')
        self.assertEqual(read_counters(frame),
                         {'diamonds': (0, 10), 'emeralds': (0, 10)})
        self.assertEqual(read_counters(png_frame(FIXTURES / 'new_goods_d2_e0.png')),
                         {'diamonds': (2, 10), 'emeralds': (0, 10)})
        with self.assertRaises(MacroError):
            read_counters(png_frame(FIXTURES / 'unknown_goods_counters.png'))

    def test_live_two_diamonds_raster_is_calibrated_from_labelled_capture(self):
        frame = png_frame(FIXTURES / 'live-diamonds-2-emeralds-0-masked.png')
        self.assertEqual(read_counters(frame),
                         {'diamonds': (2, 10), 'emeralds': (0, 10)})

    def test_live_eight_counters_are_not_misread_as_zero(self):
        frame = png_frame(FIXTURES / 'live-diamonds-8-emeralds-8-masked.png')
        self.assertEqual(read_counters(frame),
                         {'diamonds': (8, 10), 'emeralds': (8, 10)})

    def test_live_final_nine_and_ten_counters_are_recognized(self):
        frame = png_frame(FIXTURES / 'live-diamonds-9-emeralds-10-masked.png')
        self.assertEqual(read_counters(frame),
                         {'diamonds': (9, 10), 'emeralds': (10, 10)})

    def test_nearby_masks_for_same_count_do_not_create_false_ambiguity(self):
        frame = png_frame(FIXTURES / 'new_goods_d0_e0_live_masked.png')
        data = profiles()
        template = next(sample['mask'] for sample in data['counter_templates']
                        if sample.get('evidence_frame') == 'new_goods_d0_e0_live_masked.png'
                        and len(sample['mask'][0]) == 39)
        near = list(template)
        row = list(near[5])
        index = next(i for i, value in enumerate(row) if value == '0')
        row[index] = '1'
        near[5] = ''.join(row)
        data['counter_templates'] = [
            {'used': 0, 'total': 10, 'mask': template},
            {'used': 0, 'total': 10, 'mask': near},
        ]
        self.assertEqual(read_counter(frame, 'diamonds', data), (0, 10))

    def test_nearby_masks_for_different_counts_remain_ambiguous(self):
        frame = png_frame(FIXTURES / 'new_goods_d0_e0_live_masked.png')
        data = profiles()
        template = next(sample['mask'] for sample in data['counter_templates']
                        if sample.get('evidence_frame') == 'new_goods_d0_e0_live_masked.png'
                        and len(sample['mask'][0]) == 39)
        near = list(template)
        # Make two plausible calibrations, each a few pixels from the actual
        # capture, with distances close enough to exercise the ambiguity guard.
        for y, x in ((5, 1), (5, 2), (6, 1)):
            row = list(near[y])
            row[x] = '1' if row[x] == '0' else '0'
            near[y] = ''.join(row)
        second = list(template)
        for y, x in ((5, 3), (5, 4), (6, 2), (6, 3)):
            row = list(second[y])
            row[x] = '1' if row[x] == '0' else '0'
            second[y] = ''.join(row)
        data['counter_templates'] = [
            {'used': 0, 'total': 10, 'mask': near},
            {'used': 1, 'total': 10, 'mask': second},
        ]
        with self.assertRaises(MacroError):
            read_counter(frame, 'diamonds', data)

    def test_ad_button_recognizes_recorded_and_shifted_goods_layouts(self):
        runner = ShopRunner(mock.Mock(), 'Slayer Legend')
        old = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        shifted = png_frame(FIXTURES / 'new_ad_buttons_shifted_masked.png')
        for kind in ('diamonds', 'emeralds'):
            with self.subTest(kind=kind, layout='recorded'):
                profile = runner.data['ad_buttons'][kind]
                self.assertIs(runner._ad_button(old, kind), profile)
                self.assertTrue(runner._ad_ready(old, kind))
            with self.subTest(kind=kind, layout='shifted'):
                variant = runner.data['ad_buttons'][kind]['variants'][0]
                self.assertIs(runner._ad_button(shifted, kind), variant)
                self.assertTrue(runner._ad_ready(shifted, kind))

    def test_claim_click_uses_center_of_uniquely_matched_free_button(self):
        old = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        shifted = png_frame(FIXTURES / 'new_ad_buttons_shifted_masked.png')
        counts = {'diamonds': (0, 10), 'emeralds': (0, 10)}
        for kind, current_click in (('diamonds', (356, 395)), ('emeralds', (356, 467))):
            for layout, frame, click in (
                ('recorded', old, (343, 375) if kind == 'diamonds' else (353, 446)),
                ('shifted', shifted, current_click),
            ):
                with self.subTest(kind=kind, layout=layout):
                    backend = mock.Mock()
                    runner = ShopRunner(backend, 'Slayer Legend',
                                        sleep=lambda _seconds: None, clock=lambda: 1.0)
                    runner._observe = mock.Mock(return_value=(counts, frame))
                    runner._wait_for_increment = mock.Mock(return_value=(
                        {'diamonds': (1, 10), 'emeralds': (0, 10)} if kind == 'diamonds'
                        else {'diamonds': (0, 10), 'emeralds': (1, 10)}, frame))
                    runner._claim_once(7, kind, counts, frame)
                    backend.click.assert_called_once_with(7, click[0], click[1], False)
                    self.assertLess(click[1], 500)

    def test_batch_clicks_are_bounded_to_remaining_slots_and_known_free_controls(self):
        counts = {'diamonds': (8, 10), 'emeralds': (9, 10)}
        for frame, positions in (
            (png_frame(FIXTURES / 'recording_claim_before_d0_e0.png'),
             [(343, 375)] * 2 + [(353, 446)]),
            (png_frame(FIXTURES / 'goods-current-diamonds-10.png'),
             [(356, 395)] * 2 + [(356, 467)]),
        ):
            backend = mock.Mock()
            backend.capture.return_value=frame
            runner = ShopRunner(backend, 'Slayer Legend')
            runner._check_cancel = mock.Mock()
            # Isolate the batch bound from the caller's calibrated Goods entry.
            real_matching=matching_screens
            def calibrated_goods(current,screens):
                return ['shop_goods'] if screens==[runner.goods] else real_matching(current,screens)
            with mock.patch('league_bot.slayer.shop.read_counters',return_value=counts), mock.patch(
                    'league_bot.slayer.shop.matching_screens',side_effect=calibrated_goods):
                clicked = runner._click_batch(7, counts, frame)
            self.assertEqual(clicked, {'diamonds': 2, 'emeralds': 1})
            self.assertEqual([(call.args[1], call.args[2])
                              for call in backend.click.call_args_list], positions)
            self.assertEqual(runner._check_cancel.call_count, 3)

    def test_batch_skips_unavailable_kind_and_never_clicks_paid_offer(self):
        frame = png_frame(FIXTURES / 'paid_offers_only_masked.png')
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend')
        self.assertEqual(runner._click_batch(7, {'diamonds': (0, 10),
                                                  'emeralds': (0, 10)}, frame), {'diamonds': 0, 'emeralds': 0})
        backend.click.assert_not_called()

        old = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        runner._ad_button = mock.Mock(side_effect=lambda _frame, kind:
            runner.data['ad_buttons'][kind] if kind == 'emeralds' else None)
        self.assertEqual(runner._click_batch(7, {'diamonds': (0, 10),
                                                  'emeralds': (8, 10)}, old), {'diamonds': 0, 'emeralds': 2})
        self.assertEqual([(call.args[1], call.args[2])
                          for call in backend.click.call_args_list], [(353, 446)] * 2)

    def test_batch_checks_cancellation_before_every_click(self):
        frame = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend')
        runner._check_cancel = mock.Mock(side_effect=[None, None, MacroCancelled('cancelled')])
        with self.assertRaises(MacroCancelled):
            runner._click_batch(7, {'diamonds': (0, 10), 'emeralds': (0, 10)}, frame)
        self.assertEqual(backend.click.call_count, 2)
        self.assertEqual(runner._check_cancel.call_count, 3)

    def test_batch_records_only_stable_observed_partial_progress(self):
        runner = ShopRunner(mock.Mock(), 'Slayer Legend')
        before = {'diamonds': (8, 10), 'emeralds': (9, 10)}
        partial = {'diamonds': (9, 10), 'emeralds': (9, 10)}
        final_frame = object()
        runner._click_batch = mock.Mock(return_value={'diamonds': 2, 'emeralds': 1})
        runner._observe = mock.Mock(return_value=(partial, final_frame))
        runner._record = mock.Mock()
        after, frame = runner._run_batch(7, before, object())
        self.assertEqual(after, partial)
        self.assertIs(frame, final_frame)
        self.assertEqual(runner._observe.call_count, 2)
        runner._record.assert_called_once_with(18, 'macro')
        self.assertEqual((runner.outcome.progress, runner.outcome.acquired,
                          runner.outcome.deferred), (18, 1, True))

    def test_paid_offer_only_and_ambiguous_ad_layouts_never_click(self):
        paid = png_frame(FIXTURES / 'paid_offers_only_masked.png')
        counts = {'diamonds': (0, 10), 'emeralds': (0, 10)}
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend')
        self.assertIsNone(runner._ad_button(paid, 'diamonds'))
        runner._observe = mock.Mock(return_value=(counts, paid))
        with self.assertRaises(MacroError):
            runner._claim_once(7, 'diamonds', counts, paid)
        backend.click.assert_not_called()

    def test_partial_batch_finishes_remaining_in_same_panel(self):
        runner = ShopRunner(mock.Mock(), 'Slayer Legend')
        before = {'diamonds': (8, 10), 'emeralds': (8, 10)}
        partial = {'diamonds': (9, 10), 'emeralds': (9, 10)}
        final = {'diamonds': (10, 10), 'emeralds': (10, 10)}
        runner._click_batch = mock.Mock(side_effect=[
            {'diamonds': 2, 'emeralds': 2}, {'diamonds': 1, 'emeralds': 1}])
        runner._observe = mock.Mock(side_effect=[(partial, 'partial'), (final, 'final')])
        runner._record = mock.Mock()
        self.assertEqual(runner._run_batch(7, before, 'initial'), (final, 'final'))
        self.assertEqual(runner._click_batch.call_args_list,
                         [mock.call(7, before, 'initial'), mock.call(7, partial, 'partial')])
        self.assertEqual((runner.outcome.progress, runner.outcome.acquired), (20, 4))
        self.assertFalse(runner.outcome.skipped)

    def test_final_counter_cannot_advance_an_unclicked_offer(self):
        runner = ShopRunner(mock.Mock(), 'Slayer Legend')
        before = {'diamonds': (8, 10), 'emeralds': (8, 10)}
        runner._click_batch = mock.Mock(return_value={'diamonds': 2, 'emeralds': 0})
        runner._observe = mock.Mock(return_value=(
            {'diamonds': (10, 10), 'emeralds': (10, 10)}, 'final'))
        runner._record = mock.Mock()
        counts, _ = runner._run_batch(7, before, 'initial')
        self.assertEqual(counts, before)
        self.assertTrue(runner.outcome.skipped)
        runner._record.assert_not_called()

        recorded = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        backend = mock.Mock()
        runner = ShopRunner(backend, 'Slayer Legend')
        profile = runner.data['ad_buttons']['diamonds']
        profile['variants'].append({'click': {'x': 356, 'y': 395},
                                    'anchors': profile['anchors']})
        self.assertIsNone(runner._ad_button(recorded, 'diamonds'))
        runner._observe = mock.Mock(return_value=(counts, recorded))
        with self.assertRaises(MacroError):
            runner._claim_once(7, 'diamonds', counts, recorded)
        backend.click.assert_not_called()

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
        for used in (7, 8, 9):
            distance = min(_mask_distance(observed, sample['mask'])
                           for sample in data['counter_templates'] if sample['used'] == used)
            if used == 8:
                self.assertEqual(distance, 0)
            else:
                self.assertGreater(distance, 0)

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

    def test_increment_wait_tolerates_one_unexpected_frame_but_rejects_two(self):
        before = png_frame(FIXTURES / 'recording_claim_before_d0_e0.png')
        transient = png_frame(FIXTURES / 'new_goods_d2_e0.png')
        expected = png_frame(FIXTURES / 'recording_claim_after_d1_e0.png')

        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.side_effect = [transient, expected, expected]
        now = [0.0]
        runner = ShopRunner(backend, 'Slayer Legend',
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
        after, _ = runner._wait_for_increment(
            7, {'diamonds': (0, 10), 'emeralds': (0, 10)}, 'diamonds', timeout=2)
        self.assertEqual(after, {'diamonds': (1, 10), 'emeralds': (0, 10)})

        backend = mock.Mock()
        backend.client_size.return_value = (434, 810)
        backend.capture.side_effect = [transient, transient]
        now = [0.0]
        runner = ShopRunner(backend, 'Slayer Legend',
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds), clock=lambda: now[0])
        with self.assertRaisesRegex(MacroError, 'contador desconhecido'):
            runner._wait_for_increment(
                7, {'diamonds': (0, 10), 'emeralds': (0, 10)}, 'diamonds', timeout=2)

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
        final = {'diamonds': (10, 10), 'emeralds': (10, 10)}
        runner._ensure_goods = mock.Mock(return_value=7)
        runner._observe = mock.Mock(return_value=(initial, None))
        runner._ad_ready = mock.Mock(return_value=True)
        def run_batch(hwnd, counts, frame):
            runner.outcome=ShopOutcome(20, acquired=2)
            return final, frame
        runner._run_batch = mock.Mock(side_effect=run_batch)
        with mock.patch('league_bot.macro.MacroRunner._do_screen_flow', return_value=7):
            runner._do_screen_flow({'free_item_shop': True}, 7)
        self.assertEqual(runner.outcome.progress, 20)
        self.assertEqual(runner.outcome.acquired, 2)
        self.assertFalse(runner.outcome.skipped)
        runner._run_batch.assert_called_once_with(7, initial, None)

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
