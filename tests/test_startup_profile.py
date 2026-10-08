import json
from pathlib import Path
import unittest

from league_bot.imaging import Frame
from league_bot.macro import MacroError, MacroRunner, load_macro
from league_bot.screens import matching_screens
from tests.fakes import FakeBackend, FakeTime

ROOT = Path(__file__).resolve().parent.parent


def reference_frame(reference):
    width, height = reference['size']
    row_size = ((width * 3 + 3) // 4) * 4
    pixels = bytearray(row_size * height)
    for x, y, (r, g, b) in reference['pixels']:
        offset = (height - 1 - y) * row_size + x * 3
        pixels[offset:offset+3] = bytes((b, g, r))
    return Frame(width, height, bytes(pixels))


class CalibratedStartupTests(unittest.TestCase):
    def setUp(self):
        self.steps = load_macro(ROOT / 'macros/start_game_recognized.json')
        self.flow = next(step for step in self.steps if step['action'] == 'screen_flow')
        samples = json.loads((ROOT / 'tests/fixtures/startup/real_patches.json').read_text(encoding='utf-8'))
        self.samples = {sample['name']: sample for sample in samples}
        self.frames = {name: reference_frame(sample) for name, sample in self.samples.items()}

    def test_observed_patches_identify_only_the_correct_screen(self):
        for name, sample in self.samples.items():
            with self.subTest(name=name):
                self.assertEqual(matching_screens(self.frames[name], self.flow['screens']), sample['expected'])

    def replay(self, names):
        backend = FakeBackend(size=(434, 810))
        frames = [self.frames[name] for name in names]
        def capture(hwnd):
            return frames.pop(0) if len(frames) > 1 else frames[0]
        backend.capture = capture
        clock = FakeTime()
        runner = MacroRunner(backend, 'Slayer Legend', foreground=True, sleep=clock.sleep, clock=clock.clock)
        runner.run(self.steps)
        return backend

    def test_real_patch_sequence_with_save_confirms_once_then_finishes(self):
        backend = self.replay(['tap_reference', 'tap_background', 'tap_clicked',
                               'save_reference', 'save_confirmed_pre', 'save_confirmed',
                               'after_save', 'post_login', 'main_reference'])
        self.assertEqual(backend.clicks(), [(217, 405, False), (138, 655, False)])
        self.assertTrue(backend.minimized)
        self.assertLess(backend.calls.index(('move_resize', None, None, 438, 814)),
                        backend.calls.index(('click', 217, 405, False)))

    def test_save_can_be_absent_and_an_already_open_main_needs_no_clicks(self):
        backend = self.replay(['tap_reference', 'tap_background', 'tap_clicked', 'post_login', 'main_reference'])
        self.assertEqual(backend.clicks(), [(217, 405, False)])
        self.assertEqual(self.replay(['post_login', 'main_reference']).clicks(), [])

    def test_wrong_geometry_stops_before_any_click(self):
        backend = FakeBackend(size=(561, 1036))
        clock = FakeTime()
        runner = MacroRunner(backend, 'Slayer Legend', sleep=clock.sleep, clock=clock.clock)
        with self.assertRaisesRegex(MacroError, 'calibration requires size'):
            runner.run([self.flow])
        self.assertEqual(backend.clicks(), [])


if __name__ == '__main__':
    unittest.main()
