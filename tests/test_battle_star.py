import json
import tempfile
import unittest
from pathlib import Path

from league_bot.imaging import Frame, solid_frame
from league_bot.macro import MacroCancelled, MacroError
from league_bot.slayer.battle_star import StarBattleWaiter, battle_star_present


STAR = (
    "...........###...........",
    "...........####..........",
    "........##########.......",
    ".......###########.......",
    "........#########........",
    ".........#######.........",
    ".........#######.........",
    ".........#######.........",
    ".........##...##.........",
)


def frame_with_star(shift=(0, 0)):
    base = solid_frame(434, 810, (30, 30, 30))
    data = bytearray(base.bgr)
    for y, row in enumerate(STAR, start=8):
        for x, char in enumerate(row):
            if char == "#":
                px, py = 381 + x + shift[0], 751 + y + shift[1]
                offset = (base.height - 1 - py) * base.row_size + px * 3
                data[offset:offset + 3] = bytes((255, 255, 255))
    return Frame(base.width, base.height, bytes(data))


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def pause(self, seconds):
        self.value += seconds


class FakeBackend:
    def __init__(self, frames):
        self.frames = list(frames)

    def find_window(self, title):
        return 1

    def capture(self, hwnd):
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0] if self.frames else None


class BattleStarTests(unittest.TestCase):
    def test_real_recording_panels_and_resized_frames(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is only needed to read development screenshots")
        root = Path(__file__).parents[1] / "macros/local/recordings"
        paths = [root / "cubo_de_melhora/20261010_084503_c276c305e20c4410903cd664833f5e71/0007_before.png",
                 root / "cave_treinoxp/20261011_092521_2dd080d7dd3a4b559bd25f34a4c5c407/0005_before.png",
                 root / "forest/20261016_105457_88e4b226711444b5bbdb2b982f39885e/0008_before.png",
                 root / "shelterflamedragon/20261016_104915_6aa8876ac5e24ea79c5eb83b0ad77129/0008_before.png"]
        if not all(path.exists() for path in paths):
            self.skipTest("personal source recordings are not distributed")
        for path in paths:
            with Image.open(path) as source:
                for size in ((434, 810), (868, 1620)):
                    rgb = source.convert("RGB").resize(size, Image.Resampling.NEAREST)
                    width, height = rgb.size
                    data = rgb.tobytes()
                    row_size = (width * 3 + 3) // 4 * 4
                    bgr = bytearray()
                    for y in reversed(range(height)):
                        row = data[y * width * 3:(y+1) * width * 3]
                        for x in range(0, len(row), 3):
                            bgr.extend(row[x:x+3][::-1])
                        bgr.extend(bytes(row_size - width * 3))
                    with self.subTest(path=path.name, size=size):
                        self.assertTrue(battle_star_present(Frame(width, height, bytes(bgr))))

    def test_capture_gaps_reset_return_stability(self):
        visible = frame_with_star()
        absent = solid_frame(434, 810, (30, 30, 30))
        clock = FakeClock()
        frames = [absent, absent, visible, visible, None, visible, visible, visible]
        waiter = StarBattleWaiter(FakeBackend(frames), "game", clock.pause, clock=clock)
        waiter.wait(entry_timeout=3, battle_timeout=10)
        self.assertEqual(clock.value, 7)

    def test_absent_star_times_out_without_releasing_exit(self):
        clock = FakeClock()
        waiter = StarBattleWaiter(FakeBackend([solid_frame(434, 810, (30, 30, 30))]),
                                  "game", clock.pause, clock=clock)
        with self.assertRaisesRegex(MacroError, "did not return"):
            waiter.wait(entry_timeout=3, battle_timeout=2)

    def test_detector_matches_star_shape_with_small_position_shift(self):
        self.assertTrue(battle_star_present(frame_with_star((2, -1))))
        self.assertFalse(battle_star_present(solid_frame(434, 810, (30, 30, 30))))
        self.assertFalse(battle_star_present(solid_frame(434, 810, (0, 0, 0))))

    def test_wait_requires_disappearance_then_three_present_frames(self):
        visible = frame_with_star()
        absent = solid_frame(434, 810, (30, 30, 30))
        clock = FakeClock()
        waiter = StarBattleWaiter(FakeBackend([visible, absent, absent, visible, visible, visible]),
                                  "game", clock.pause, clock=clock)
        waiter.wait(entry_timeout=4, battle_timeout=4)
        self.assertEqual(clock.value, 5.0)

    def test_persistent_star_times_out_and_saves_last_capture(self):
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            waiter = StarBattleWaiter(FakeBackend([frame_with_star()]), "game", clock.pause,
                                      clock=clock, diagnostics_dir=Path(directory))
            with self.assertRaisesRegex(MacroError, "never disappeared"):
                waiter.wait(entry_timeout=2, battle_timeout=2)
            captures = list(Path(directory).glob("battle-star-*.png"))
            self.assertEqual(len(captures), 1)
            self.assertTrue(captures[0].read_bytes().startswith(b"\x89PNG"))

    def test_capture_failure_and_black_frames_cannot_establish_entry(self):
        clock = FakeClock()
        waiter = StarBattleWaiter(FakeBackend([None, solid_frame(434, 810, (0, 0, 0))]),
                                  "game", clock.pause, clock=clock)
        with self.assertRaisesRegex(MacroError, "never disappeared"):
            waiter.wait(entry_timeout=2, battle_timeout=2)

    def test_black_content_with_bright_titlebar_is_still_ignored(self):
        frame = solid_frame(434, 810, (0, 0, 0))
        data = bytearray(frame.bgr)
        for y in range(36):
            for x in range(frame.width):
                offset = (frame.height - 1 - y) * frame.row_size + x * 3
                data[offset:offset + 3] = bytes((255, 255, 255))
        black_content = Frame(frame.width, frame.height, bytes(data))
        clock = FakeClock()
        waiter = StarBattleWaiter(FakeBackend([black_content]), "game", clock.pause, clock=clock)
        with self.assertRaisesRegex(MacroError, "never disappeared"):
            waiter.wait(entry_timeout=2, battle_timeout=2)

    def test_cancellation_from_pause_propagates(self):
        def cancel(_seconds):
            raise MacroCancelled("cancelled")

        waiter = StarBattleWaiter(FakeBackend([frame_with_star()]), "game", cancel, clock=lambda: 0)
        with self.assertRaises(MacroCancelled):
            waiter.wait()

    def test_reference_template_asset_is_rectangular(self):
        asset = Path(__file__).parents[1] / "league_bot/slayer/assets/battle-star.json"
        data = json.loads(asset.read_text(encoding="utf-8"))
        for template in data["templates"]:
            self.assertEqual(len(set(map(len, template))), 1)


if __name__ == "__main__":
    unittest.main()
