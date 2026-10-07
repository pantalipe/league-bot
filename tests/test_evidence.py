import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from league_bot.evidence import EvidenceWriter
from league_bot.imaging import solid_frame
from league_bot.recorder import Recorder
from tests.test_imaging import decode_png
from tests.test_recorder import record
from tests.fakes import FakeBackend


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "session"

    def run_recording(self, presses=None, **kwargs):
        return record(presses or [(1.0, 1.08, 5, 6)], backend=kwargs.pop("backend", FakeBackend(size=(20, 20))),
                      shots_dir=self.directory, **kwargs)[0]

    def manifest(self, result):
        return json.loads(result.shots_path.read_text(encoding="utf-8"))

    def test_pre_and_post_frames_are_linked_to_click_and_macro_step(self):
        backend = FakeBackend(size=(20, 20))

        def change_screen(now):
            if now >= 1.0:
                backend.fill = (100, 50, 25)

        result = self.run_recording(backend=backend, sleep_hook=change_screen, anchors=True)
        data = self.manifest(result)
        event = data["clicks"][0]
        self.assertEqual(result.image_count, 2)
        self.assertEqual(event["macro_step_index"], 2)
        self.assertEqual(event["position"]["x_percent"], "27.5%")
        self.assertEqual(event["window"], {"width": 20, "height": 20})
        self.assertLessEqual(event["before"]["capture_finished_seconds"], event["pressed_seconds"])
        self.assertGreaterEqual(event["after"]["capture_started_seconds"], event["released_seconds"] + 0.5)
        for phase, color in [("before", (10, 10, 10)), ("after", (100, 50, 25))]:
            snapshot = event[phase]
            self.assertEqual(snapshot["status"], "saved")
            rows = decode_png((self.directory / snapshot["file"]).read_bytes())
            self.assertEqual((len(rows[0]), len(rows)), (20, 20))
            self.assertEqual(rows[0][0], color)
        self.assertFalse(data["after_is_stable"])

    def test_fast_next_input_does_not_get_mislabeled_as_previous_result(self):
        result = self.run_recording([(1.0, 1.05, 5, 6), (1.2, 1.25, 7, 8)])
        events = self.manifest(result)["clicks"]
        self.assertEqual(events[0]["after"], {"status": "next_input", "file": None})
        self.assertEqual(events[1]["after"]["status"], "saved")
        self.assertTrue(result.warnings)

    def test_stop_before_post_delay_records_missing_post(self):
        result = self.run_recording(stop_at=1.2)
        self.assertEqual(self.manifest(result)["clicks"][0]["after"]["status"], "recording_stopped")

    def test_failed_capture_keeps_macro_with_explicit_missing_images(self):
        backend = FakeBackend(size=(20, 20))
        backend.capture = lambda hwnd: None
        result = self.run_recording(backend=backend)
        self.assertEqual(result.clicks, 1)
        self.assertEqual(result.image_count, 0)
        self.assertEqual(self.manifest(result)["clicks"][0]["before"]["status"], "capture_unavailable")
        self.assertEqual([s["action"] for s in result.steps], ["wait_window", "click"])

    def test_stale_and_resized_frames_are_not_used_as_before_evidence(self):
        for mode in ["stale", "resize"]:
            with self.subTest(mode=mode):
                backend = FakeBackend(size=(20, 20))
                def hook(now):
                    if mode == "resize" and now >= 0.99:
                        backend.size = (25, 25)
                result = self.run_recording(backend=backend, sleep_hook=hook, capture_interval=10 if mode == "stale" else 0.15,
                                            stop_at=1.2,
                                            **({} if mode == "resize" else {"poll_interval": 0.01}))
                event = self.manifest(result)["clicks"][0]
                self.assertEqual(event["before"]["status"], "window_resized" if mode == "resize" else "capture_stale")

    def test_no_clicks_or_only_drag_create_no_evidence_directory(self):
        result = self.run_recording([(1.0, 1.4, 5, 6, 19, 19)])
        self.assertEqual(result.clicks, 0)
        self.assertIsNone(result.shots_path)
        self.assertFalse(self.directory.exists())

    def test_io_failure_warns_without_discarding_macro(self):
        self.directory.write_text("a file blocks mkdir")
        result = self.run_recording()
        self.assertEqual(result.clicks, 1)
        self.assertIsNone(result.shots_path)
        self.assertEqual(result.image_count, 0)
        self.assertTrue(any("manifest.json" in w for w in result.warnings))

    def test_encoding_is_asynchronous_and_queue_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        frame = solid_frame(20, 20, (1, 2, 3))
        original = type(frame).to_png
        def slow_encode(self):
            entered.set()
            release.wait(5)
            return original(self)
        writer = EvidenceWriter(self.directory, 0.0, 0.5)
        with patch.object(type(frame), "to_png", slow_encode):
            first = writer.snapshot(1, "before", (0, 0, frame), "")
            self.assertTrue(entered.wait(2))
            snapshots = [writer.snapshot(i, "before", (0, 0, frame), "") for i in range(2, 12)]
            self.assertEqual(sum(s["status"] == "queue_full" for s in snapshots), 2)
            release.set()
            writer.finish(1.0, (20, 20), [])
        self.assertEqual(first["status"], "saved")
        self.assertEqual(writer.image_count, 9)

    def test_click_list_does_not_retain_full_pre_click_frames(self):
        build_steps = Recorder._build_steps
        checked = []
        def check(recorder, clicks):
            checked.extend(click.before for click in clicks)
            return build_steps(recorder, clicks)
        with patch.object(Recorder, "_build_steps", check):
            result = self.run_recording([(1.0, 1.08, 5, 6), (3.0, 3.08, 7, 8)])
        self.assertEqual(checked, [None, None])
        self.assertEqual(result.image_count, 4)

    def test_previous_click_state_is_not_used_as_next_before_frame(self):
        result = self.run_recording([(0.8, 0.82, 5, 6), (0.88, 0.9, 7, 8)], capture_interval=0.5)
        events = self.manifest(result)["clicks"]
        self.assertEqual(events[1]["before"]["status"], "intervening_input")


if __name__ == "__main__":
    unittest.main()
