import copy
import unittest

from league_bot.imaging import Frame
from league_bot.screens import ScreenError, matching_screens, validate_screens


def frame_from_rows(rows):
    height, width = len(rows), len(rows[0])
    row_size = ((width * 3 + 3) // 4) * 4
    data = bytearray()
    for row in reversed(rows):
        raw = b"".join(bytes((b, g, r)) for r, g, b in row)
        data.extend(raw)
        data.extend(b"\0" * (row_size - len(raw)))
    return Frame(width, height, bytes(data))


def screen(name="home", *, anchors=None, **kwargs):
    return {"name": name, "anchors": anchors if anchors is not None else [
        {"x": 0, "y": 0, "color": [10, 20, 30]},
        {"x": 1, "y": 1, "color": [200, 210, 220]},
    ], **kwargs}


class ScreenMatchingTests(unittest.TestCase):
    def test_matches_all_screens_with_all_anchors(self):
        frame = frame_from_rows([
            [(10, 20, 30), (0, 0, 0), (0, 0, 0)],
            [(0, 0, 0), (0, 0, 0), (0, 0, 0)],
            [(0, 0, 0), (0, 0, 0), (200, 210, 220)],
        ])
        configs = [screen("first"), screen("also-first"), screen("miss", anchors=[
            {"x": 0, "y": 0, "color": [10, 20, 30]},
            {"x": 1, "y": 1, "color": [0, 0, 0]},
        ])]
        self.assertEqual(matching_screens(frame, configs), ["first", "also-first"])

    def test_tolerance_radius_and_edge_coordinates(self):
        rows = [[(100, 100, 100)] * 3 for _ in range(3)]
        rows[0][0] = (110, 100, 100)
        rows[2][2] = (90, 100, 100)
        frame = frame_from_rows(rows)
        cfg = screen(anchors=[
            {"x": 0, "y": 0, "color": [100, 100, 100], "tolerance": 8, "radius": 1},
            {"x": 1, "y": 1, "color": [90, 100, 100], "tolerance": 8, "radius": 1},
        ])
        self.assertEqual(matching_screens(frame, [cfg]), ["home"])

    def test_missing_frame_has_no_match(self):
        self.assertEqual(matching_screens(None, [screen()]), [])

    def test_matching_does_not_mutate_configuration(self):
        configs = [screen()]
        original = copy.deepcopy(configs)
        matching_screens(frame_from_rows([[(10, 20, 30)] * 2, [(200, 210, 220)] * 2]), configs)
        self.assertEqual(configs, original)


class ScreenValidationTests(unittest.TestCase):
    def test_terminal_must_exist_and_have_no_click(self):
        configs = [screen("start", click={"x": "center", "y": "center"}), screen("done")]
        validate_screens(configs, "done")
        with self.assertRaises(ScreenError):
            validate_screens(configs, "unknown")
        with self.assertRaises(ScreenError):
            validate_screens([screen("done", click={"x": 1, "y": 1})], "done")

    def test_rejects_duplicate_names_and_empty_or_insufficient_anchors(self):
        with self.assertRaises(ScreenError):
            validate_screens([screen("same"), screen("same")], "same")
        with self.assertRaises(ScreenError):
            validate_screens([screen("empty", anchors=[])], "empty")
        with self.assertRaises(ScreenError):
            validate_screens([screen("one", anchors=[{"x": 0, "y": 0, "color": [0, 0, 0]}])], "one")

    def test_rejects_invalid_anchor_values(self):
        invalid_anchors = [
            {"x": True, "y": 0, "color": [0, 0, 0]},
            {"x": float("nan"), "y": 0, "color": [0, 0, 0]},
            {"x": 0, "y": 1.1, "color": [0, 0, 0]},
            {"x": 0, "y": 0, "color": [True, 0, 0]},
            {"x": 0, "y": 0, "color": [0, 256, 0]},
            {"x": 0, "y": 0, "color": [0, 0, 0], "tolerance": True},
            {"x": 0, "y": 0, "color": [0, 0, 0], "radius": 21},
        ]
        for bad in invalid_anchors:
            with self.subTest(anchor=bad), self.assertRaises(ScreenError):
                validate_screens([screen(anchors=[bad, {"x": 1, "y": 1, "color": [0, 0, 0]}])], "home")

    def test_rejects_bad_click_shape_and_boolean_max_clicks(self):
        for cfg in (screen(click=None), screen(click={"x": 1}), screen(max_clicks=True), screen(max_clicks=0)):
            with self.subTest(config=cfg), self.assertRaises(ScreenError):
                validate_screens([cfg], "home")


if __name__ == "__main__":
    unittest.main()
