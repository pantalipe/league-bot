"""Offline recognition and empty-mailbox safety tests."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from league_bot.slayer.mailbox import MailboxRunner, _stock_entry_prefix, load_profiles

if la.available():
    from league_bot.imaging import Frame, solid_frame
    from league_bot.macro import MacroError, MacroRunner
    from league_bot.screens import matching_screens

FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "mailbox"
WIDTH, HEIGHT = 434, 810


def png_frame(path: Path) -> Frame:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    row_size = ((width * 3 + 3) // 4) * 4
    rgb = image.tobytes()
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        start = y * width * 3
        for offset in range(start, start + width * 3, 3):
            row.extend((rgb[offset + 2], rgb[offset + 1], rgb[offset]))
        row.extend(b"\x00" * (row_size - width * 3))
        pixels.extend(row)
    return Frame(width, height, bytes(pixels))


class FakeTime:
    def __init__(self): self.now = 0.0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakeBackend:
    def __init__(self, frames): self.frames, self.click_log = list(frames), []
    def is_window(self, hwnd): return hwnd == 7
    def find_window(self, _title): return 7
    def client_size(self, _hwnd): return WIDTH, HEIGHT
    def capture(self, _hwnd): return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
    def click(self, hwnd, x, y, foreground): self.click_log.append((x, y, foreground))
    def is_minimized(self, _hwnd): return False


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.profiles = load_profiles()
        self.empty = png_frame(FIXTURES / "empty.png")
        self.populated = png_frame(FIXTURES / "populated.png")

    def runner(self, frames):
        clock = FakeTime()
        return MailboxRunner(FakeBackend(frames), "Slayer Legend", True,
            sleep=clock.sleep, clock=clock.clock, claim_steps=[{"action": "wait", "seconds": .1}])

    def test_masked_recordings_distinguish_empty_and_populated(self):
        screens = self.profiles["screens"]
        self.assertEqual(matching_screens(self.empty, [screens[0]]), ["mailbox_panel"])
        self.assertEqual(matching_screens(self.empty, [screens[2]]), ["mailbox_empty"])
        self.assertEqual(matching_screens(self.empty, [screens[1]]), [])
        self.assertEqual(matching_screens(self.populated, [screens[0]]), ["mailbox_panel"])
        self.assertEqual(matching_screens(self.populated, [screens[1]]), ["mailbox_populated"])
        self.assertEqual(matching_screens(self.populated, [screens[2]]), [])

    def test_empty_waits_stably_closes_recognized_panel_and_never_claims(self):
        runner = self.runner([self.empty, self.empty])
        flows = []
        runner._flow = lambda hwnd, terminal, screens, timeout=40: flows.append((terminal, screens)) or hwnd
        with mock.patch.object(MacroRunner, "_do_screen_flow", return_value=7), \
             mock.patch.object(MacroRunner, "run") as run:
            runner._do_screen_flow({"mailbox_collection": True}, 7)
        self.assertEqual(runner.outcome.progress, 1)
        self.assertTrue(runner.outcome.empty)
        self.assertIn("vazio", str(runner.outcome))
        run.assert_not_called()
        self.assertEqual(len(flows), 2)
        self.assertEqual(flows[-1][0], "main")
        close = flows[-1][1][0]
        self.assertNotIn("home_close_mailbox", [s["name"] for s in flows[-1][1]])
        self.assertEqual(matching_screens(self.empty, flows[-1][1]), ["mailbox_close_empty"])
        self.assertEqual(close["click"], {"x": 390, "y": 85})
        self.assertEqual(runner._backend.click_log, [])

    def test_populated_keeps_recorded_claim_suffix_and_does_not_retry(self):
        claim_steps = [{"action": "wait_for_pixel", "x": "82.14%", "y": "29.69%", "color": [239, 190, 128]},
                       {"action": "click", "x": "82.14%", "y": "29.69%"}]
        runner = MailboxRunner(FakeBackend([self.populated, self.populated]), "Slayer Legend", True,
            sleep=lambda _s: None, clock=lambda: 0, claim_steps=claim_steps)
        runner._flow = lambda hwnd, *_args, **_kwargs: hwnd
        with mock.patch.object(MacroRunner, "_do_screen_flow", return_value=7), \
             mock.patch.object(MacroRunner, "run") as run:
            runner._do_screen_flow({"mailbox_collection": True}, 7)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], claim_steps)
        self.assertFalse(runner.outcome.empty)

    def test_unknown_state_fails_closed(self):
        black = solid_frame(WIDTH, HEIGHT, (0, 0, 0))
        runner = self.runner([black])
        with self.assertRaises(MacroError):
            runner._observe_state(7, timeout=.7)
        self.assertEqual(runner._backend.click_log, [])

    def test_custom_prefix_is_left_to_recorder_without_changing_tail(self):
        macro = json.loads((ROOT / "league_bot/slayer/macros/mailbox.json").read_text())
        self.assertTrue(_stock_entry_prefix(macro["steps"]))
        custom = copy.deepcopy(macro["steps"])
        custom[2]["x"] = "91%"
        self.assertFalse(_stock_entry_prefix(custom))
        self.assertEqual(custom[7:], macro["steps"][7:])

    def test_custom_macro_falls_back_unchanged_and_factory_is_preserved(self):
        macro = json.loads((ROOT / "league_bot/slayer/macros/mailbox.json").read_text())
        macro["steps"][2]["x"] = "91%"
        sentinel = object()
        class Library:
            def load_steps(self, _name): return copy.deepcopy(macro["steps"])
        class Game:
            _status_store = None
            _runner_factory = sentinel
            _library = Library()
            def _exclusive(self): return nullcontext()
            def _title(self): return "Slayer Legend"
            def load_macro_steps(self, _name): return copy.deepcopy(macro["steps"])
            def _run_steps(self, steps, *_args): self.ran = steps
        game = Game()
        from league_bot.slayer.mailbox import run_mailbox
        self.assertIsNone(run_mailbox(game))
        self.assertEqual(game.ran, macro["steps"])
        self.assertIs(game._runner_factory, sentinel)

    def test_factory_is_restored_after_stock_flow_failure(self):
        macro = json.loads((ROOT / "league_bot/slayer/macros/mailbox.json").read_text())
        sentinel = object()
        class Library:
            def load_steps(self, _name): return copy.deepcopy(macro["steps"])
        class Game:
            _status_store = None
            _runner_factory = sentinel
            _library = Library()
            def _exclusive(self): return nullcontext()
            def _title(self): return "Slayer Legend"
            def final_steps(self): return []
            def _run_steps(self, *_args): raise MacroError("expected test failure")
        game = Game()
        from league_bot.slayer.mailbox import run_mailbox
        with self.assertRaises(MacroError): run_mailbox(game)
        self.assertIs(game._runner_factory, sentinel)


if __name__ == "__main__":
    unittest.main()
