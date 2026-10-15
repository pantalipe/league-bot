"""Real navigation screen-flow tests for the daily attendance check."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
if la.available():
    from league_bot.imaging import Frame
    from league_bot.macro import MacroError, MacroRunner
    from league_bot.screens import matching_screens
    from test_slayer_attendance import FakeBackend, FakeTime, png_frame


FIXTURES = ROOT / "tests" / "fixtures" / "slayer"


def frame_with_main_anchors(path: Path, anchors: list[dict]) -> Frame:
    """The main-menu fixture is partial; add only calibrated UI anchor samples."""
    image = Image.open(path).convert("RGB")
    pixels = image.load()
    width, height = image.size
    for anchor in anchors:
        x = round(anchor["x"] * (width - 1))
        y = round(anchor["y"] * (height - 1))
        color = tuple(anchor["color"])
        radius = anchor.get("radius", 0)
        for py in range(max(0, y - radius), min(height, y + radius + 1)):
            for px in range(max(0, x - radius), min(width, x + radius + 1)):
                pixels[px, py] = color

    # Reuse the fixture conversion from the attendance tests without creating a
    # temporary file or changing the checked-in screenshot.
    rgb = image.tobytes()
    row_size = ((width * 3 + 3) // 4) * 4
    raw = bytearray()
    for y in range(height - 1, -1, -1):
        start = y * width * 3
        row = bytearray()
        for offset in range(start, start + width * 3, 3):
            row.extend((rgb[offset + 2], rgb[offset + 1], rgb[offset]))
        row.extend(b"\x00" * (row_size - width * 3))
        raw.extend(row)
    return Frame(width, height, bytes(raw))


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class DailyAttendanceNavigationTests(unittest.TestCase):
    def make_game(self, backend):
        self.time = FakeTime()
        configured = la.load_settings(
            environ={"SLAYER_WINDOW_TITLE": "Slayer Legend"}, env_file=None,
        )
        settings = SimpleNamespace(**configured.__dict__)
        settings.foreground_input = True
        return la.HomeSlayerGame(
            settings, backend,
            runner_factory=lambda b, title, foreground, log: MacroRunner(
                b, title, foreground, log, sleep=self.time.sleep, clock=self.time.clock,
            ),
        )

    def navigation_frames(self, *tail):
        settings = la.load_settings(
            environ={"SLAYER_WINDOW_TITLE": "Slayer Legend"}, env_file=None,
        )
        game = la.HomeSlayerGame(settings, backend=object())
        startup = game.load_macro_steps("start_game_recognized")
        main = next(screen for step in startup if step["action"] == "screen_flow"
                    for screen in step["screens"] if screen["name"] == "main")
        nav = la.load_daily_navigation()
        main_frame = frame_with_main_anchors(
            FIXTURES / "main-menu.png", main["anchors"] + nav["main_closed_anchors"],
        )
        return [main_frame] * 4 + [
            main_frame if name == "main-menu" else png_frame(FIXTURES / f"{name}.png")
            for name in tail
        ]

    def test_claim_ready_navigation_returns_claimed_and_restores_window(self):
        # Entry flow: main -> menu -> settings -> attendance panel. The second
        # flow claims once and follows the modal/settings/menu back to main.
        backend = FakeBackend(self.navigation_frames(
            "menu-open", "menu-open", "settings", "settings",
            "attendance-settings", "attendance-settings",
            "attendance-ready", "attendance-ready", "attendance-ready", "attendance-ready",
            "attendance-claimed", "attendance-claimed",
            "settings", "settings", "menu-open", "menu-open",
            "main-menu", "main-menu",
        ))
        game = self.make_game(backend)

        result = game.check_attendance()

        self.assertEqual(result, "claimed")
        self.assertEqual(backend.click_log, [
            (408, 59, False), (375, 60, False), (218, 267, False),
            (217, 610, False), (217, 712, False), (375, 165, False),
            (408, 60, False),
        ])
        self.assertEqual(
            [call for call in backend.calls if call[0] == "move_resize"],
            [("move_resize", None, None, 438, 814),
             ("move_resize", 1460, 202, 438, 814)],
        )
        self.assertEqual(backend.calls[-1], ("minimize",))

    def test_entry_profile_matches_only_the_current_navigation_state(self):
        settings = la.load_settings(
            environ={"SLAYER_WINDOW_TITLE": "Slayer Legend"}, env_file=None,
        )
        game = la.HomeSlayerGame(settings, backend=object())
        startup = game.load_macro_steps("start_game_recognized")
        main = next(screen for step in startup if step["action"] == "screen_flow"
                    for screen in step["screens"] if screen["name"] == "main")
        nav = la.load_daily_navigation()
        screens = [main, nav["menu_open"], nav["settings_open"], nav["attendance_open"]]
        frames = [
            frame_with_main_anchors(
                FIXTURES / "main-menu.png", main["anchors"] + nav["main_closed_anchors"],
            ),
            png_frame(FIXTURES / "menu-open.png"),
            png_frame(FIXTURES / "settings.png"),
            png_frame(FIXTURES / "attendance-settings.png"),
        ]
        expected = [["main"], ["menu_open"], ["settings_open"], ["attendance_open"]]
        self.assertEqual([matching_screens(frame, screens) for frame in frames], expected)

    def test_current_menu_rendering_completes_attendance_navigation(self):
        nav = la.load_daily_navigation()
        current = png_frame(FIXTURES / "menu-open-current.png")
        self.assertEqual(matching_screens(current, [nav["menu_open"], nav["settings_open"],
                                                   nav["attendance_open"]]), ["menu_open"])
        backend = FakeBackend(self.navigation_frames(
            "menu-open-current", "menu-open-current", "settings-current", "settings-current",
            "attendance-settings", "attendance-settings",
            "attendance-ready-current", "attendance-ready-current",
            "attendance-claimed", "attendance-claimed",
            "settings-current", "settings-current", "menu-open-current", "menu-open-current",
            "main-menu", "main-menu",
        ))
        self.assertEqual(self.make_game(backend).check_attendance(), "claimed")
        self.assertEqual(backend.click_log, [
            (408, 59, False), (375, 60, False), (218, 267, False),
            (217, 610, False), (217, 712, False), (375, 165, False), (408, 60, False),
        ])

    def test_already_claimed_panel_only_closes_and_returns_to_main(self):
        backend = FakeBackend(self.navigation_frames(
            "menu-open", "menu-open", "settings", "settings",
            "attendance-settings", "attendance-settings",
            "attendance-claimed", "attendance-claimed",
            "settings", "settings", "menu-open", "menu-open",
            "main-menu", "main-menu",
        ))
        game = self.make_game(backend)

        self.assertEqual(game.check_attendance(), "already_claimed")
        self.assertEqual(backend.click_log, [
            (408, 59, False), (375, 60, False), (218, 267, False),
            (217, 712, False), (375, 165, False), (408, 60, False),
        ])
        self.assertEqual(backend.calls[-1], ("minimize",))

    def test_unknown_screen_times_out_without_clicking(self):
        from league_bot.imaging import solid_frame
        backend = FakeBackend(self.navigation_frames() + [
            # Main is recognized and opened once; unknown frames never trigger
            # guessed navigation clicks after that transition.
            solid_frame(434, 810, (0, 0, 0)),
        ])
        # Keep the fake clock deterministic while shortening the real flow deadline.
        game = self.make_game(backend)
        original_load = game.load_macro_steps

        def quick_load(name):
            steps = original_load(name)
            for step in steps:
                if step["action"] == "screen_flow":
                    step["timeout"] = 1
            return steps

        game.load_macro_steps = quick_load
        with self.assertRaisesRegex(MacroError, "timed out"):
            game.check_attendance()
        self.assertEqual(backend.click_log, [(408, 59, False)])


if __name__ == "__main__":
    unittest.main()
