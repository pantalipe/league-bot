"""Policy and calibrated-screen tests for the guild-pet flow."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
import league_bot.slayer.pet as slayer_pet
from league_bot.slayer.pet import PetRunner, remaining_cost

if la.available():
    from league_bot.imaging import Frame, solid_frame
    from league_bot.macro import MacroCancelled, MacroError, MacroRunner


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "pet"
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
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeBackend:
    def __init__(self, frames):
        self.frames = list(frames)
        self.click_log = []
        self.hwnd = 7

    def find_window(self, _title):
        return self.hwnd

    def is_window(self, hwnd):
        return hwnd == self.hwnd

    def client_size(self, _hwnd):
        return WIDTH, HEIGHT

    def is_minimized(self, _hwnd):
        return False

    def capture(self, _hwnd):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def click(self, hwnd, x, y, foreground):
        self.click_log.append((x, y, foreground))

    def restore(self, _hwnd):
        pass

    def minimize(self, _hwnd):
        pass

    def move_resize(self, *_args):
        pass

    def poll_input(self, *_args):
        return None


class RecordingStore:
    def __init__(self):
        self.progress = []
        self.errors = []

    def mark_progress(self, task, progress, goal, **kwargs):
        self.progress.append((task, progress, goal, kwargs))

    def mark_error(self, task, message, **kwargs):
        self.errors.append((task, message, kwargs))

    def cycle_id(self):
        return "cycle"


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class PetPolicyTests(unittest.TestCase):
    def make_runner(self, *, start=0, balances=(), store=None):
        """Keep PetRunner's real _do_screen_flow policy; stub game navigation only."""
        time = FakeTime()
        runner = PetRunner(
            FakeBackend([]), "Slayer Legend", foreground=True,
            sleep=time.sleep, clock=time.clock, store=store, cycle="cycle",
            balance_reader=lambda _frame: 0,
        )
        state = {"progress": start, "balances": list(balances), "events": []}

        def enter(hwnd):
            state["events"].append(("enter", state["progress"]))
            return hwnd

        def exit_pet(hwnd):
            state["events"].append(("exit", state["progress"]))
            return hwnd

        def counter(hwnd):
            state["events"].append(("counter", state["progress"]))
            return hwnd, state["progress"]

        def balance(hwnd):
            value = state["balances"].pop(0)
            state["events"].append(("balance", state["progress"], value))
            if isinstance(value, BaseException):
                raise value
            return hwnd, value

        def flow(hwnd, terminal, _screens):
            state["events"].append(("flow", terminal, state["progress"]))
            if terminal.startswith("pet_") and terminal[4:].isdigit():
                next_progress = int(terminal[4:])
                if next_progress == state["progress"] + 1:
                    if state["progress"] > 0:
                        state["events"].append(("paid", state["progress"]))
                    state["progress"] = next_progress
            return hwnd

        runner._enter = enter
        runner._exit = exit_pet
        runner._counter = counter
        runner._balance = balance
        runner._flow = flow
        return runner, state

    def run_policy(self, runner):
        # The guild-pet step always begins by recovering the home screen. Policy
        # tests start at the pet counter, so bypass only that introductory flow.
        with mock.patch.object(MacroRunner, "_do_screen_flow", autospec=True, return_value=7):
            return runner._do_screen_flow({"guild_pet": True}, 7)

    def test_costs_for_every_confirmed_progress_value(self):
        self.assertEqual([remaining_cost(n) for n in range(6)], [1000, 1000, 900, 700, 400, 0])

    def test_free_and_all_paid_cleans_require_a_fresh_balance_before_each_paid_click(self):
        runner, state = self.make_runner(start=0, balances=[1000, 900, 700, 400])
        self.run_policy(runner)
        events = state["events"]
        paid_positions = [i for i, event in enumerate(events) if event[0] == "paid"]
        for progress, paid_position in enumerate(paid_positions, start=1):
            balance_position = max(i for i, event in enumerate(events[:paid_position])
                                   if event[0] == "balance")
            self.assertLess(balance_position, paid_position)
            self.assertEqual(events[balance_position][1], progress)
            self.assertEqual(events[balance_position][2], remaining_cost(progress))
        self.assertEqual(len(paid_positions), 4)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertFalse(runner.outcome.skipped)

    def test_balance_999_collects_free_then_skips_all_paid_cleans(self):
        runner, state = self.make_runner(start=0, balances=[999])
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 1)
        self.assertTrue(runner.outcome.skipped)
        self.assertIn("999", runner.outcome.reason)
        self.assertEqual([event for event in state["events"] if event[0] == "paid"], [])

    def test_progress_two_requires_cost_of_all_remaining_paid_cleans(self):
        runner, state = self.make_runner(start=2, balances=[699])
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 2)
        self.assertTrue(runner.outcome.skipped)
        self.assertEqual([event for event in state["events"] if event[0] == "paid"], [])

    def test_already_complete_does_not_read_balance_or_pay(self):
        runner, state = self.make_runner(start=5, balances=[])
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertEqual([event for event in state["events"] if event[0] == "balance"], [])
        self.assertEqual([event for event in state["events"] if event[0] == "paid"], [])

    def test_unreadable_balance_fails_before_any_paid_action(self):
        runner, state = self.make_runner(start=1, balances=[MacroError("balance unreadable")])
        with self.assertRaisesRegex(MacroError, "balance unreadable"):
            self.run_policy(runner)
        self.assertEqual([event for event in state["events"] if event[0] == "paid"], [])

    def test_cancel_during_balance_check_stops_before_paid_action(self):
        runner, state = self.make_runner(start=1, balances=[MacroCancelled("cancelled")])
        with self.assertRaises(MacroCancelled):
            self.run_policy(runner)
        self.assertEqual([event for event in state["events"] if event[0] == "paid"], [])

    def test_partial_visual_progress_is_persisted(self):
        store = RecordingStore()
        runner, _state = self.make_runner(start=0, balances=[1000, MacroError("unreadable")], store=store)
        with self.assertRaisesRegex(MacroError, "unreadable"):
            self.run_policy(runner)
        self.assertEqual([row[1] for row in store.progress], [0, 1, 2])
        self.assertTrue(all(row[0] == slayer_pet.TASK and row[2] == 5 for row in store.progress))
        self.assertTrue(all(row[3]["source"] == "visual" for row in store.progress))

    def test_unknown_counter_frame_and_ambiguous_profiles_never_authorize_a_click(self):
        runner, _state = self.make_runner(start=0, balances=[])
        runner._last_frame = solid_frame(WIDTH, HEIGHT, (0, 0, 0))
        with mock.patch.object(slayer_pet, "matching_screens", return_value=[]):
            with self.assertRaisesRegex(MacroError, "desconhecido; nenhum gasto autorizado"):
                PetRunner._counter(runner, 7)

        runner, _state = self.make_runner(start=0, balances=[])
        runner._last_frame = png_frame(FIXTURES / "pet_0.png")
        with mock.patch.object(slayer_pet, "matching_screens", return_value=["pet_0", "pet_1"]):
            with self.assertRaisesRegex(MacroError, "desconhecido; nenhum gasto autorizado"):
                PetRunner._counter(runner, 7)


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class PetCalibratedScreenTests(unittest.TestCase):
    def test_changed_cost_does_not_authorize_paid_click(self):
        from league_bot.screens import matching_screens
        from PIL import ImageDraw
        from test_slayer_cube import png_image_frame
        image = Image.open(FIXTURES / "pet_1.png").convert("RGB")
        ImageDraw.Draw(image).rectangle((178,617,258,638),fill=(0,0,0))
        frame = png_image_frame(image)
        counters = [s for s in slayer_pet.load_screens() if s["name"].startswith("pet_") and s["name"][4:].isdigit()]
        self.assertEqual(matching_screens(frame,counters),[])

    def test_balance_requires_two_equal_reads_and_rejects_instability(self):
        from test_slayer_cube import cube_frame
        time = FakeTime()
        reader = mock.Mock(side_effect=[1000,999])
        backend = FakeBackend([cube_frame("main")])
        runner = PetRunner(backend,"Slayer Legend",sleep=time.sleep,clock=time.clock,balance_reader=reader)
        with self.assertRaisesRegex(MacroError,"instavel"):
            runner._balance(7)
        self.assertEqual(reader.call_count,2)
        self.assertEqual(backend.click_log,[])

    def test_counter_and_reward_fixtures_uniquely_match_profiles(self):
        from league_bot.screens import matching_screens

        profiles = slayer_pet.load_screens()
        for number in range(6):
            frame = png_frame(FIXTURES / f"pet_{number}.png")
            counters = [screen for screen in profiles if screen["name"].startswith("pet_")
                        and screen["name"][4:].isdigit()]
            self.assertEqual(matching_screens(frame, counters), [f"pet_{number}"])
        self.assertEqual(matching_screens(png_frame(FIXTURES / "reward.png"), profiles), ["reward"])

    def test_persistent_paid_counter_fixture_is_clicked_at_most_once_by_real_screen_flow(self):
        profile = copy.deepcopy(next(s for s in slayer_pet.load_screens() if s["name"] == "pet_1"))
        profile["click"] = {"x": 216, "y": 651}
        frame = png_frame(FIXTURES / "pet_1.png")
        backend = FakeBackend([frame])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=True,
                           sleep=time.sleep, clock=time.clock, balance_reader=lambda _frame: 0)
        terminal = copy.deepcopy(next(s for s in slayer_pet.load_screens() if s["name"] == "pet_5"))
        step = {"action": "screen_flow", "terminal": "pet_5", "timeout": 1,
                "poll_seconds": .1, "stable_frames": 2,
                "frame_size": [WIDTH, HEIGHT], "screens": [profile, terminal]}
        with self.assertRaisesRegex(MacroError, "timed out.*pet_1"):
            runner.run([step])
        self.assertEqual(backend.click_log, [(216, 651, False)])
