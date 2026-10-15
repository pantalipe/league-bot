import json
import tempfile
import unittest
from pathlib import Path

from league_bot.geometry import ReferenceBackend, clip_viewport, load_geometry_profile, map_point, normalize_frame, wrap_backend
from league_bot.imaging import Frame


def frame_from_rows(rows):
    """Build bottom-up BGR Frame data from top-down rows of grayscale values."""
    height, width = len(rows), len(rows[0])
    stride = ((width * 3 + 3) // 4) * 4
    data = bytearray(stride * height)
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            offset = (height - 1 - y) * stride + x * 3
            data[offset:offset + 3] = bytes((value, value, value))
    return Frame(width, height, bytes(data))


class FakeBackend:
    def __init__(self):
        self.size = (500, 1000)
        self.surface = (25, 50, 450, 900)
        self.clicks = []
        self.moves = []
        self.image = frame_from_rows([[1] * 500 for _ in range(1000)])

    def client_size(self, hwnd):
        return self.size

    def viewport(self, hwnd):
        return self.surface

    def capture(self, hwnd):
        return self.image

    def click(self, hwnd, x, y, foreground):
        self.clicks.append((hwnd, x, y, foreground))

    def move_position(self, hwnd, x, y):
        self.moves.append((hwnd, x, y))

    def move_resize(self, hwnd, x, y, width, height):
        raise AssertionError("preserve_size should not call move_resize")


class GeometryTests(unittest.TestCase):
    def test_viewport_clips_small_child_overflow_to_root_client(self):
        self.assertEqual(clip_viewport((0, 36), (438, 778), (434, 810)), (0, 36, 434, 774))
        with self.assertRaisesRegex(ValueError, "too far"):
            clip_viewport((0, 36), (443, 778), (434, 810))
        with self.assertRaisesRegex(ValueError, "origin"):
            clip_viewport((-1, 36), (438, 778), (434, 810))

    def test_same_geometry_preserves_clicks_and_pixels(self):
        source = frame_from_rows([[1, 2], [3, 4]])
        normalized = normalize_frame(source, (2, 2))
        self.assertIs(normalized, source)
        self.assertEqual([normalized.pixel(x, y)[0] for y in range(2) for x in range(2)], [1, 2, 3, 4])
        self.assertEqual(map_point(1, 1, (2, 2), (2, 2)), (1, 1))

    def test_same_geometry_partial_viewport_returns_original_frame(self):
        source = frame_from_rows([[1, 2], [3, 4]])
        self.assertIs(normalize_frame(source, (2, 2), (0, 1, 2, 1), (0, 1, 2, 1)), source)

    def test_maps_scale_and_translation_inside_viewport(self):
        ref = (100, 200)
        target = (500, 1000)
        rv = (5, 10, 90, 180)
        tv = (20, 30, 450, 900)
        self.assertEqual(map_point(10, 20, ref, target, rv, tv), (45, 80))
        self.assertEqual(map_point(94, 189, ref, target, rv, tv), (465, 925))

    def test_refuses_reference_points_outside_game_viewport(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            map_point(2, 0, (10, 10), (20, 20), (3, 2, 5, 6), (0, 0, 10, 12))

    def test_capture_crops_header_and_resamples_viewport(self):
        source = frame_from_rows([[10, 10, 10], [20, 21, 22], [30, 31, 32], [40, 40, 40]])
        result = normalize_frame(source, (2, 2), (0, 0, 2, 2), (1, 1, 2, 2))
        self.assertEqual([result.pixel(x, y)[0] for y in range(2) for x in range(2)], [21, 22, 31, 32])

    def test_unknown_incompatible_aspect_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            normalize_frame(frame_from_rows([[1, 2], [3, 4]]), (2, 3))

    def test_rejects_distorted_calibrated_live_viewport(self):
        backend = FakeBackend()
        backend.surface = (20, 30, 400, 900)  # 0.444 vs 0.5 reference viewport
        adapter = ReferenceBackend(backend, (100, 200), (0, 0, 100, 200))
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            adapter.click(7, 50, 100, False)

    def test_adapter_uses_fresh_live_viewport_and_preserves_foreground_flag(self):
        backend = FakeBackend()
        adapter = ReferenceBackend(backend, (100, 200), (0, 0, 100, 200))
        adapter.click(7, 50, 100, False)
        self.assertEqual(backend.clicks, [(7, 250, 500, False)])
        backend.surface = (40, 60, 400, 800)
        adapter.click(7, 50, 100, True)
        self.assertEqual(backend.clicks[-1], (7, 240, 460, True))

    def test_preserve_size_moves_without_resizing(self):
        backend = FakeBackend()
        adapter = ReferenceBackend(backend, (434, 810), (0, 32, 434, 778))
        self.assertIsNone(adapter.move_resize(7, None, None, 434, 810))
        adapter.move_resize(7, 90, 120, 434, 810)
        self.assertEqual(backend.moves, [(7, 90, 120)])

    def test_profile_is_optional_validated_and_wraps_opt_in(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as directory:
            self.assertIs(wrap_backend(backend, directory), backend)
            profile_path = Path(directory) / "calibration" / "geometry.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps({
                "version": 1,
                "reference_size": [434, 810],
                "reference_viewport": [0, 32, 434, 778],
            }), encoding="utf-8")
            profile = load_geometry_profile(directory)
            self.assertEqual(profile["reference_viewport"], (0, 32, 434, 778))
            self.assertIsInstance(wrap_backend(backend, directory), ReferenceBackend)

    def test_recorder_input_is_mapped_back_into_reference_space(self):
        from league_bot.backend import InputSample
        backend = FakeBackend()
        backend.poll_input = lambda *_: InputSample(250,500,True,True,True)
        adapter = ReferenceBackend(backend,(100,200),(0,0,100,200))
        sample = adapter.poll_input(7,121)
        self.assertEqual((sample.x,sample.y),(50,100))
        self.assertTrue(sample.left_down)
        self.assertTrue(sample.stop_pressed)
        backend.poll_input = lambda *_: InputSample(10,10,True,False)
        self.assertFalse(adapter.poll_input(7,121).inside)

    def test_profile_requires_calibrated_reference_viewport(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "calibration" / "geometry.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps({"version": 1, "reference_size": [434, 810]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference_size and reference_viewport"):
                load_geometry_profile(directory)


if __name__ == "__main__":
    unittest.main()
