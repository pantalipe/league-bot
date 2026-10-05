import time
import unittest

from league_bot.macro import MacroRunner, resolve_coord, validate_steps
from league_bot.recorder import MAX_TAP_SECONDS, Recorder, RecorderError, vk_from_name
from tests.fakes import FakeBackend, FakeTime, ScriptedMouse
from tests.test_imaging import frame_from_rows

TITLE = "Slayer Legend"
TWO_TAPS = [(1.0, 1.08, 200, 400), (4.0, 4.08, 100, 200)]


def record(presses, stop_at=6.0, backend=None, sleep_hook=None, **kwargs):
    clock = FakeTime()
    backend = backend or FakeBackend()
    backend.input_fn = ScriptedMouse(clock.clock, presses, stop_at, size=backend.size)

    def sleep(seconds):
        clock.sleep(seconds)
        if sleep_hook:
            sleep_hook(clock.now)

    kwargs.setdefault("background_capture", False)
    recorder = Recorder(backend, TITLE, clock=clock.clock, sleep=sleep, **kwargs)
    return recorder.record(), backend, recorder


class StepGenerationTests(unittest.TestCase):
    def test_with_anchors_taps_become_wait_anchor_and_click_steps(self):
        recording, _, _ = record(TWO_TAPS, anchors=True)
        actions = [s["action"] for s in recording.steps]
        self.assertEqual(actions, ["wait_window", "wait_for_pixel", "click", "wait", "wait_for_pixel", "click"])
        self.assertEqual(recording.clicks, 2)
        self.assertEqual(recording.window_size, (400, 800))
        wait = recording.steps[3]["seconds"]
        self.assertAlmostEqual(wait, 3.0 - 0.4, places=1)  # recorded gap minus the replayed click's own duration

    def test_anchor_carries_the_color_seen_before_the_click(self):
        recording, _, _ = record(TWO_TAPS, anchors=True)
        anchors = [s for s in recording.steps if s["action"] == "wait_for_pixel"]
        self.assertTrue(all(a["color"] == [10, 10, 10] for a in anchors))
        self.assertTrue(all(a["radius"] == 2 for a in anchors))

    def test_anchors_replay_on_screens_where_a_single_pixel_differs_from_its_surroundings(self):
        # alternating dark/bright columns: the exact pixel at x=10 is 0 but the 5x5 mean is 80
        rows = [[(0, 0, 0) if x % 2 == 0 else (200, 200, 200) for x in range(20)] for _ in range(20)]
        frame = frame_from_rows(rows)
        backend = FakeBackend(size=(20, 20))
        backend.capture = lambda hwnd: frame
        recording, _, _ = record([(1.0, 1.08, 10, 10)], stop_at=3.0, backend=backend, anchors=True)
        self.assertEqual([s["color"] for s in recording.steps if s["action"] == "wait_for_pixel"], [[80, 80, 80]])
        replay, clock = FakeBackend(size=(20, 20)), FakeTime()
        replay.capture = lambda hwnd: frame
        MacroRunner(replay, TITLE, True, sleep=clock.sleep, clock=clock.clock).run(recording.steps)
        self.assertEqual(replay.clicks(), [(10, 10, True)])

    def test_default_is_just_waits_and_clicks_and_never_captures_the_screen(self):
        recording, backend, _ = record(TWO_TAPS)
        self.assertEqual([s["action"] for s in recording.steps], ["wait_window", "click", "wait", "click"])
        self.assertNotIn(("capture",), backend.calls)

    def test_clicks_without_a_frame_still_record_but_have_no_anchor(self):
        backend = FakeBackend()
        backend.capture = lambda hwnd: None
        recording, _, _ = record(TWO_TAPS, backend=backend, anchors=True)
        self.assertEqual(recording.clicks, 2)
        self.assertNotIn("wait_for_pixel", [s["action"] for s in recording.steps])

    def test_quick_successive_taps_need_no_wait_step(self):
        recording, _, _ = record([(1.0, 1.05, 200, 400), (1.3, 1.35, 210, 410)], anchors=False)
        self.assertEqual([s["action"] for s in recording.steps], ["wait_window", "click", "click"])

    def test_recording_replays_to_the_same_pixels(self):
        recording, _, _ = record(TWO_TAPS, anchors=True)
        validate_steps(recording.steps)
        backend, clock = FakeBackend(), FakeTime()
        MacroRunner(backend, TITLE, True, sleep=clock.sleep, clock=clock.clock).run(recording.steps)
        self.assertEqual(backend.clicks(), [(200, 400, True), (100, 200, True)])

    def test_replay_round_trip_holds_for_every_pixel_of_a_small_window(self):
        for size in [(438, 814), (7, 13)]:
            backend = FakeBackend(size=size)
            presses = [(1.0 + 2 * i, 1.08 + 2 * i, x, y) for i, (x, y) in enumerate([(0, 0), (size[0] - 1, size[1] - 1), (size[0] // 2, 3)])]
            recording, _, _ = record(presses, stop_at=9.0, backend=backend, anchors=False)
            expected = [(x, y, True) for (_, _, x, y) in presses]
            replay, clock = FakeBackend(size=size), FakeTime()
            MacroRunner(replay, TITLE, True, sleep=clock.sleep, clock=clock.clock).run(recording.steps)
            self.assertEqual(replay.clicks(), expected)
            self.assertEqual(resolve_coord(recording.steps[1]["x"], size[0]), presses[0][2])


class GestureTests(unittest.TestCase):
    def test_drags_are_skipped_and_counted(self):
        recording, _, _ = record([(1.0, 1.3, 200, 400, 200, 700), (3.0, 3.08, 100, 200)])
        self.assertEqual((recording.clicks, recording.skipped_gestures), (1, 1))

    def test_long_holds_are_skipped(self):
        recording, _, _ = record([(1.0, 1.0 + MAX_TAP_SECONDS + 0.5, 200, 400)])
        self.assertEqual((recording.clicks, recording.skipped_gestures), (0, 1))

    def test_clicks_outside_the_game_window_are_ignored(self):
        recording, _, _ = record([(1.0, 1.08, 500, 400), (2.0, 2.08, 200, 900), (3.0, 3.08, 200, 400)])
        self.assertEqual(recording.clicks, 1)

    def test_a_button_held_when_recording_starts_is_ignored(self):
        recording, _, _ = record([(-1.0, 0.5, 200, 400), (2.0, 2.08, 100, 200)])
        self.assertEqual((recording.clicks, recording.skipped_gestures), (1, 0))


class StoppingTests(unittest.TestCase):
    def test_stop_key_ends_recording_before_later_clicks(self):
        recording, _, _ = record([(1.0, 1.08, 200, 400), (4.0, 4.08, 100, 200)], stop_at=2.0)
        self.assertEqual(recording.clicks, 1)
        self.assertLess(recording.duration, 2.5)

    def test_stop_method_ends_recording(self):
        clock, backend = FakeTime(), FakeBackend()
        backend.input_fn = ScriptedMouse(clock.clock, TWO_TAPS)

        def sleep(seconds):
            clock.sleep(seconds)
            if clock.now > 2.0:
                recorder.stop()

        recorder = Recorder(backend, TITLE, clock=clock.clock, sleep=sleep, background_capture=False)
        self.assertEqual(recorder.record().clicks, 1)

    def test_time_limit(self):
        recording, _, _ = record(TWO_TAPS, stop_at=None, max_seconds=2.0)
        self.assertEqual(recording.clicks, 1)
        self.assertTrue(any("limit" in w for w in recording.warnings))

    def test_window_closing_ends_recording_with_a_warning(self):
        backend = FakeBackend()

        def close_window(now):
            if now > 2.0:
                backend.alive = False

        recording, _, _ = record(TWO_TAPS, stop_at=None, backend=backend, sleep_hook=close_window)
        self.assertEqual(recording.clicks, 1)
        self.assertTrue(any("closed" in w for w in recording.warnings))

    def test_missing_window_is_an_error(self):
        backend = FakeBackend()
        backend.hide_for = 100
        with self.assertRaisesRegex(RecorderError, "not found"):
            Recorder(backend, TITLE).record()

    def test_stop_key_names(self):
        self.assertEqual(vk_from_name("F10"), 0x79)
        self.assertEqual(vk_from_name(" f1 "), 0x70)
        self.assertEqual(vk_from_name("F12"), 0x7B)
        for bad in ["F13", "F0", "esc", "10", ""]:
            with self.subTest(key=bad), self.assertRaises(RecorderError):
                vk_from_name(bad)


class BackgroundCaptureTests(unittest.TestCase):
    def test_real_clock_with_the_capture_thread(self):
        backend = FakeBackend()
        origin = time.monotonic()
        backend.input_fn = ScriptedMouse(lambda: time.monotonic() - origin, [(0.3, 0.38, 200, 400)], stop_at=0.6)
        recording = Recorder(backend, TITLE, anchors=True, capture_interval=0.05).record()
        self.assertEqual(recording.clicks, 1)
        anchors = [s for s in recording.steps if s["action"] == "wait_for_pixel"]
        self.assertEqual([a["color"] for a in anchors], [[10, 10, 10]])


if __name__ == "__main__":
    unittest.main()
