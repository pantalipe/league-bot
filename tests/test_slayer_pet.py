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
from league_bot.slayer.pet import PetRunner

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
    def make_runner(self, *, start=0, store=None):
        """Keep PetRunner's real _do_screen_flow policy; stub game navigation only."""
        time = FakeTime()
        runner = PetRunner(
            FakeBackend([]), "Slayer Legend", foreground=True,
            sleep=time.sleep, clock=time.clock, store=store, cycle="cycle",
        )
        state = {"progress": start, "events": []}

        def enter(hwnd):
            state["events"].append(("enter", state["progress"]))
            return hwnd

        def exit_pet(hwnd):
            state["events"].append(("exit", state["progress"]))
            return hwnd

        def counter(hwnd):
            state["events"].append(("counter", state["progress"]))
            return hwnd, state["progress"]

        def flow(hwnd, terminal, _screens):
            state["events"].append(("flow", terminal, state["progress"]))
            return hwnd

        def clean_batch(hwnd, progress, count, *, confirm_rewards=True):
            state["events"].append(("batch", progress, count, confirm_rewards))
            for _ in range(count):
                if progress > 0:
                    state["events"].append(("paid", progress))
                state["events"].append(("click", 216, 651))
                if confirm_rewards:
                    state["events"].append(("click", 216, 660))
                progress += 1
            state["progress"] = progress
            return hwnd, count

        def final_progress(hwnd, *, starting_progress, max_progress=None, timeout=40):
            state["events"].append(("final", starting_progress, max_progress, timeout))
            sequence = state.get("observed_sequence", [])
            observed = sequence.pop(0) if sequence else state.get("observed_final", state["progress"])
            state["progress"] = observed
            return hwnd, observed

        runner._enter = enter
        runner._exit = exit_pet
        runner._counter = counter
        runner._flow = flow
        runner._clean_batch = clean_batch
        runner._final_progress = final_progress
        return runner, state

    def run_policy(self, runner):
        # The guild-pet step always begins by recovering the home screen. Policy
        # tests start at the pet counter, so bypass only that introductory flow.
        with mock.patch.object(MacroRunner, "_do_screen_flow", autospec=True, return_value=7):
            return runner._do_screen_flow({"guild_pet": True}, 7)

    def test_zero_progress_cleans_to_five_in_one_panel_visit(self):
        store = RecordingStore()
        runner, state = self.make_runner(start=0, store=store)
        with mock.patch("league_bot.slayer.diamonds.read_diamonds",
                        side_effect=AssertionError("pet flow must not read balance")) as reader:
            self.run_policy(runner)
        reader.assert_not_called()
        events = state["events"]
        self.assertEqual([event for event in events if event[0] == "batch"], [("batch", 0, 5, True)])
        self.assertEqual(len([event for event in events if event[0] == "click"]), 2 * (5 - 0))
        self.assertEqual(len([event for event in events if event[0] == "final"]), 1)
        self.assertEqual(len([event for event in events if event[0] == "enter"]), 1)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertFalse(runner.outcome.skipped)
        self.assertEqual([row[1] for row in store.progress], [0, 5])

    def test_progress_two_cleans_remaining_three_in_one_panel_visit(self):
        runner, state = self.make_runner(start=2)
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertFalse(runner.outcome.skipped)
        self.assertEqual([event for event in state["events"] if event[0] == "batch"], [("batch", 2, 3, True)])
        self.assertEqual(len([event for event in state["events"] if event[0] == "click"]), 2 * (5 - 2))
        self.assertEqual(len([event for event in state["events"] if event[0] == "enter"]), 1)

    def test_initial_quota_five_exits_without_clean_click(self):
        runner, state = self.make_runner(start=5)
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertEqual([event for event in state["events"] if event[0] == "batch"], [])
        self.assertEqual([event for event in state["events"] if event[0] == "click"], [])

    def test_already_complete_store_skips_ocr_balance_and_navigation(self):
        store = RecordingStore()
        store.snapshot = lambda: {"tasks": {slayer_pet.TASK: {"progress": 5, "target": 5}}}
        runner, state = self.make_runner(start=0, store=store)
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertEqual([event for event in state["events"] if event[0] == "enter"], [])

    def test_only_stable_final_progress_is_persisted_after_the_batch(self):
        store = RecordingStore()
        runner, state = self.make_runner(start=0, store=store)
        state["observed_sequence"] = [3, 3, 3]
        state["observed_final"] = 3
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 3)
        self.assertTrue(runner.outcome.skipped)
        batches = [event for event in state["events"] if event[0] == "batch"]
        self.assertEqual(batches[0], ("batch", 0, 5, True))
        self.assertGreater(len(batches), 2)
        self.assertTrue(all(event == ("batch", 3, 2, True) for event in batches[1:]))
        self.assertEqual(store.progress[0][1], 0)
        self.assertTrue(all(row[1] == 3 for row in store.progress[1:]))
        self.assertTrue(all(row[0] == slayer_pet.TASK and row[2] == 5 for row in store.progress))
        self.assertTrue(all(row[3]["source"] == "visual" for row in store.progress))

    def test_advancing_followup_burst_completes_from_confirmed_progress_without_new_budget_read(self):
        store = RecordingStore()
        runner, state = self.make_runner(start=0, store=store)
        state["observed_sequence"] = [3, 5]
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertFalse(runner.outcome.skipped)
        self.assertEqual([event for event in state["events"] if event[0] == "batch"],
                         [("batch", 0, 5, True), ("batch", 3, 2, True)])
        self.assertEqual([event for event in state["events"] if event[0] == "enter"],
                         [("enter", 0)])
        self.assertEqual([row[1] for row in store.progress], [0, 3, 5])

    def test_initial_counter_five_skips_all_clicks_and_balance_reader_is_not_an_api(self):
        runner, state = self.make_runner(start=5)
        self.assertNotIn("balance_reader", __import__("inspect").signature(PetRunner).parameters)
        with self.assertRaises(TypeError):
            PetRunner(FakeBackend([]), "Slayer Legend", balance_reader=lambda _frame: 0)
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 5)
        self.assertFalse(any(event[0] == "batch" for event in state["events"]))

    def test_no_progress_until_timeout_leaves_actual_counter_pending(self):
        store = RecordingStore()
        runner, state = self.make_runner(start=2, store=store)
        state["observed_final"] = 2
        self.run_policy(runner)
        self.assertEqual(runner.outcome.progress, 2)
        self.assertTrue(runner.outcome.skipped)
        self.assertGreater(len([event for event in state["events"] if event[0] == "batch"]), 1)
        self.assertTrue(store.progress)
        self.assertTrue(all(row[1] == 2 for row in store.progress))

    def test_unknown_counter_frame_and_ambiguous_profiles_never_authorize_a_click(self):
        runner, _state = self.make_runner(start=0)
        runner._last_frame = solid_frame(WIDTH, HEIGHT, (0, 0, 0))
        with mock.patch.object(slayer_pet, "matching_screens", return_value=[]):
            with self.assertRaisesRegex(MacroError, "desconhecido; nenhum gasto autorizado"):
                PetRunner._counter(runner, 7)

        runner, _state = self.make_runner(start=0)
        runner._last_frame = png_frame(FIXTURES / "pet_0.png")
        with mock.patch.object(slayer_pet, "matching_screens", return_value=["pet_0", "pet_1"]):
            with self.assertRaisesRegex(MacroError, "desconhecido; nenhum gasto autorizado"):
                PetRunner._counter(runner, 7)

        runner, state = self.make_runner(start=0)
        def unknown_counter(_hwnd):
            raise MacroError("Contador ou custo do pet da guild desconhecido; nenhum gasto autorizado.")
        runner._counter = unknown_counter
        with self.assertRaisesRegex(MacroError, "desconhecido"):
            self.run_policy(runner)
        self.assertEqual([event for event in state["events"] if event[0] == "batch"], [])
        self.assertEqual([event for event in state["events"] if event[0] == "click"], [])

    def test_real_batch_caps_to_known_remaining_and_preserves_clean_reward_click_order(self):
        backend = FakeBackend([])
        runner = PetRunner(backend, "Slayer Legend", foreground=False,
                           sleep=FakeTime().sleep, clock=FakeTime().clock)
        hwnd, count = runner._clean_batch(7, progress=4, count=99, confirm_rewards=False)
        self.assertEqual((hwnd, count), (7, 1))
        self.assertEqual(backend.click_log, [(216, 651, False)])

    def test_cancellation_is_checked_between_each_click_in_a_batch(self):
        backend = FakeBackend([])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=False,
                           sleep=time.sleep, clock=time.clock)
        original_click = backend.click
        def cancel_after_first_click(hwnd, x, y, foreground):
            original_click(hwnd, x, y, foreground)
            runner._cancelled.set()
        backend.click = cancel_after_first_click
        with self.assertRaises(MacroCancelled):
            runner._clean_batch(7, progress=0, count=1)
        self.assertEqual(backend.click_log, [(216, 651, False)])

    def test_final_observation_confirms_only_actual_counter_and_bounded_reward(self):
        reward = png_frame(FIXTURES / "reward_confirm_live.png")
        pet_1 = png_frame(FIXTURES / "pet_1.png")
        backend = FakeBackend([reward, reward, pet_1, pet_1])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=False,
                           sleep=time.sleep, clock=time.clock)
        _hwnd, progress = runner._final_progress(7, starting_progress=0, max_progress=1)
        self.assertEqual(progress, 1)
        self.assertEqual(backend.click_log, [(216, 660, False)])

    def test_final_counter_decrease_fails_without_a_confirmation_click(self):
        pet_2 = png_frame(FIXTURES / "pet_2.png")
        backend = FakeBackend([pet_2, pet_2])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=False,
                           sleep=time.sleep, clock=time.clock)
        with self.assertRaisesRegex(MacroError, "diminuiu"):
            runner._final_progress(7, starting_progress=3, max_progress=5)
        self.assertEqual(backend.click_log, [])

    def test_live_free_counter_and_button_color_are_recognized_without_relaxing_paid_states(self):
        live = png_frame(FIXTURES / "pet_0_live.png")
        data = slayer_pet.load_screens()
        candidates = [next(screen for screen in data if screen["name"] == f"pet_{n}")
                      for n in range(6)]
        self.assertEqual(slayer_pet.matching_screens(live, candidates), ["pet_0"])
        paid = next(screen for screen in data if screen["name"] == "pet_1")
        self.assertTrue(all(anchor["tolerance"] == 10 for anchor in paid["anchors"]))
        time = FakeTime()
        runner = PetRunner(FakeBackend([live, live]), "Slayer Legend", foreground=False,
                           sleep=time.sleep, clock=time.clock)
        runner._last_frame = live
        _hwnd, progress = runner._counter(7)
        self.assertEqual(progress, 0)
        self.assertEqual(runner._backend.click_log, [])


@unittest.skipUnless(la.available(), "league_bot nao encontrado (LEAGUE_BOT_DIR)")
class PetCalibratedScreenTests(unittest.TestCase):
    def test_guild_pet_navigation_retries_once_after_three_seconds(self):
        guild_frame = png_frame(FIXTURES / "guild.png")
        backend = FakeBackend([guild_frame])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=True,
                           sleep=time.sleep, clock=time.clock)
        guild = copy.deepcopy(runner.profiles["guild"])
        pet_open = runner.profiles["pet_open"]
        # Keep the introductory navigation at its already-reached guild
        # terminal, then model one missed tab click followed by success.
        with mock.patch("league_bot.slayer.guild_navigation.guild_entry_step",
                        return_value={"terminal": "guild", "screens": [guild]}):
            def matching(_frame, screens):
                names = {screen["name"] for screen in screens}
                if "pet_open" not in names:
                    return ["guild"]
                if len(backend.click_log) >= 2:
                    return ["pet_open"]
                return ["guild"]

            with mock.patch("league_bot.macro.matching_screens", side_effect=matching):
                runner._enter(7)

        self.assertEqual(backend.click_log, [(181, 773, False), (181, 773, False)])
        self.assertGreaterEqual(time.now, 3)
        self.assertEqual(runner.profiles["pet_0"].get("max_clicks", 1), 1)
        self.assertNotIn("retry_after_seconds", runner.profiles["pet_0"])

    def test_changed_cost_does_not_authorize_paid_click(self):
        from league_bot.screens import matching_screens
        from PIL import ImageDraw
        from test_slayer_cube import png_image_frame
        image = Image.open(FIXTURES / "pet_1.png").convert("RGB")
        ImageDraw.Draw(image).rectangle((178,617,258,638),fill=(0,0,0))
        frame = png_image_frame(image)
        counters = [s for s in slayer_pet.load_screens() if s["name"].startswith("pet_") and s["name"][4:].isdigit()]
        self.assertEqual(matching_screens(frame,counters),[])

    def test_counter_and_reward_fixtures_uniquely_match_profiles(self):
        from league_bot.screens import matching_screens

        profiles = slayer_pet.load_screens()
        for number in range(6):
            frame = png_frame(FIXTURES / f"pet_{number}.png")
            counters = [screen for screen in profiles if screen["name"].startswith("pet_")
                        and screen["name"][4:].isdigit()]
            self.assertEqual(matching_screens(frame, counters), [f"pet_{number}"])
        self.assertEqual(matching_screens(png_frame(FIXTURES / "reward.png"), profiles), ["reward"])

    def test_live_reward_fixture_uniquely_matches_and_confirmation_is_bounded(self):
        from league_bot.screens import matching_screens

        profiles = slayer_pet.load_screens()
        reward = next(screen for screen in profiles if screen["name"] == "reward")
        live = png_frame(FIXTURES / "reward_confirm_live.png")
        self.assertEqual(matching_screens(live, profiles), ["reward"])
        self.assertEqual(reward["click"], {"x": 216, "y": 660})
        self.assertEqual(reward["max_clicks"], 2)
        self.assertEqual(reward["retry_after_seconds"], 2.0)

        # Reward remains visible after the first confirmation, then the claimed
        # counter appears. The screen-flow may retry only that recognized modal.
        frames = [live] * 8 + [
                  png_frame(FIXTURES / "pet_1.png"),
                  png_frame(FIXTURES / "pet_1.png")]
        backend = FakeBackend(frames)
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=True,
                           sleep=time.sleep, clock=time.clock)
        step = {"action": "screen_flow", "terminal": "pet_1", "timeout": 8,
                "poll_seconds": .5, "stable_frames": 2, "frame_size": [WIDTH, HEIGHT],
                "screens": [reward, next(s for s in profiles if s["name"] == "pet_1")]}
        runner.run([step])
        self.assertEqual(backend.click_log, [(216, 660, False), (216, 660, False)])

    def test_persistent_paid_counter_fixture_is_clicked_at_most_once_by_real_screen_flow(self):
        profile = copy.deepcopy(next(s for s in slayer_pet.load_screens() if s["name"] == "pet_1"))
        profile["click"] = {"x": 216, "y": 651}
        frame = png_frame(FIXTURES / "pet_1.png")
        backend = FakeBackend([frame])
        time = FakeTime()
        runner = PetRunner(backend, "Slayer Legend", foreground=True,
                           sleep=time.sleep, clock=time.clock)
        terminal = copy.deepcopy(next(s for s in slayer_pet.load_screens() if s["name"] == "pet_5"))
        step = {"action": "screen_flow", "terminal": "pet_5", "timeout": 1,
                "poll_seconds": .1, "stable_frames": 2,
                "frame_size": [WIDTH, HEIGHT], "screens": [profile, terminal]}
        with self.assertRaisesRegex(MacroError, "timed out.*pet_1"):
            runner.run([step])
        self.assertEqual(backend.click_log, [(216, 651, False)])
