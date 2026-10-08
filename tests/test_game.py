import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from league_bot.config import Settings
from league_bot.game import GameBusy, GameError, SlayerGame
from league_bot.library import LibraryError
from league_bot.macro import MacroError, MacroRunner
from league_bot.recorder import Recorder, RecorderError, Recording
from tests.fakes import FakeBackend, FakeTime, ScriptedMouse


class Result:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class FakeRun:
    """Replaces subprocess.run for tasklist / taskkill."""

    def __init__(self, tasklist="", kill_codes=None):
        self.tasklist = tasklist
        self.kill_codes = kill_codes or {}
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == "tasklist":
            return Result(self.tasklist)
        return Result("", self.kill_codes.get(command[2], 0))


RUNNING = '"System","4","Services","0","100 K"\r\n"client.exe","1234","Console","1","50,000 K"\r\n'
NOT_RUNNING = '"System","4","Services","0","100 K"\r\n"chrome.exe","99","Console","1","9 K"\r\n'


class GameTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.macros = Path(self.tmp.name)
        self.write_macro("mini", [{"action": "wait_window", "timeout": 5}, {"action": "minimize"}])
        self.settings = Settings(window_title="Slayer Legend", start_macro="mini", macros_dir=self.macros)
        self.backend = FakeBackend()
        self.clock = FakeTime()
        self.run_cmd = FakeRun(tasklist=NOT_RUNNING)
        self.launched = []

    def write_macro(self, name, steps, sub=""):
        directory = self.macros / sub if sub else self.macros
        directory.mkdir(exist_ok=True)
        (directory / f"{name}.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")

    def make_game(self, **overrides):
        def runner_factory(backend, title, foreground, log):
            return MacroRunner(backend, title, foreground, log, sleep=self.clock.sleep, clock=self.clock.clock)

        kwargs = dict(
            run_cmd=self.run_cmd, launcher=self.launched.append,
            runner_factory=runner_factory, sleep=self.clock.sleep,
        )
        kwargs.update(overrides)
        return SlayerGame(self.settings, self.backend, **kwargs)


class ProcessTests(GameTestCase):
    def test_is_running_parses_tasklist_csv(self):
        game = self.make_game()
        self.assertFalse(game.is_running())
        self.run_cmd.tasklist = RUNNING
        self.assertTrue(game.is_running())
        self.run_cmd.tasklist = RUNNING.replace("client.exe", "CLIENT.EXE")
        self.assertTrue(game.is_running())

    def test_is_running_ignores_localized_no_match_message(self):
        self.run_cmd.tasklist = "INFORMAÇÃO: não há tarefas em execução que correspondam aos critérios.\r\n"
        self.assertFalse(self.make_game().is_running())

    def test_stop_kills_each_configured_process(self):
        message = self.make_game().stop()
        taskkills = [c for c in self.run_cmd.commands if c[0] == "taskkill"]
        self.assertEqual([c[2] for c in taskkills], ["client.exe", "crosvm.exe"])
        self.assertTrue(all(c[3:] == ["/F", "/T"] for c in taskkills))
        self.assertIn("finalizado", message)

    def test_stop_reports_when_nothing_was_running(self):
        self.run_cmd.kill_codes = {"client.exe": 128, "crosvm.exe": 128}
        self.assertIn("Nenhum processo", self.make_game().stop())

    def test_status(self):
        self.run_cmd.tasklist = RUNNING
        st = self.make_game().status()
        self.assertEqual((st.running, st.window_found, st.busy), (True, True, False))


class StartTests(GameTestCase):
    def test_screen_startup_waits_for_verified_home_before_finishing(self):
        from tests.test_screen_flow import flow
        self.write_macro("mini", [{"action": "wait_window"}, {"action": "prepare_window"},
                                  flow(), {"action": "minimize"}])
        self.backend.frames = [(v, v, v) for v in (100, 100, 150, 150, 200, 200)]
        self.make_game().start()
        self.assertEqual(self.backend.clicks(), [(200, 400, False)] * 2)
        self.assertTrue(self.backend.minimized)

    def test_uncalibrated_screen_startup_is_rejected_before_launch(self):
        from tests.test_screen_flow import flow
        step = flow()
        step["screens"][0]["anchors"] = []
        self.write_macro("mini", [{"action": "wait_window"}, step])
        with self.assertRaisesRegex(MacroError, "at least two anchors"):
            self.make_game().start()
        self.assertEqual(self.launched, [])
        self.assertEqual(self.backend.calls, [])

    def test_start_launches_then_runs_the_start_macro(self):
        message = self.make_game().start()
        self.assertEqual(self.launched, [self.settings])
        self.assertIn(("minimize",), self.backend.calls)
        self.assertIn("iniciado", message)

    def test_start_does_nothing_when_already_running(self):
        self.run_cmd.tasklist = RUNNING
        message = self.make_game().start()
        self.assertEqual(self.launched, [])
        self.assertEqual(self.backend.calls, [])
        self.assertIn("ja esta rodando", message)

    def test_shared_launcher_process_without_game_window_still_launches(self):
        self.run_cmd.tasklist = RUNNING
        self.backend.hide_for = 100
        def launch(settings):
            self.launched.append(settings)
            self.backend.hide_for = 0
        self.make_game(launcher=launch).start()
        self.assertEqual(self.launched, [self.settings])

    def test_a_broken_macro_is_caught_before_anything_is_launched(self):
        self.write_macro("mini", [{"action": "teleport"}])
        with self.assertRaises(MacroError):
            self.make_game().start()
        self.assertEqual(self.launched, [])

    def test_window_title_is_required(self):
        self.settings = replace(self.settings, window_title="")
        with self.assertRaisesRegex(GameError, "SLAYER_WINDOW_TITLE"):
            self.make_game().start()

    def test_a_second_operation_is_rejected_while_one_is_running(self):
        box = {}

        class Probe:
            def run(self, steps, name):
                try:
                    box["game"].run_macro("mini")
                except GameBusy as exc:
                    box["busy"] = exc

            def cancel(self):
                box["cancelled"] = True

        game = self.make_game(runner_factory=lambda *args: Probe())
        box["game"] = game
        game.run_macro("mini")
        self.assertIsInstance(box["busy"], GameBusy)
        # the lock is released afterwards
        game.run_macro("mini")

    def test_cancel_reaches_the_running_macro(self):
        box = {}

        class Probe:
            def run(self, steps, name):
                box["returned"] = box["game"].cancel()

            def cancel(self):
                box["cancelled"] = True

        game = self.make_game(runner_factory=lambda *args: Probe())
        box["game"] = game
        self.assertFalse(game.cancel())  # nothing running yet
        game.run_macro("mini")
        self.assertTrue(box["returned"] and box["cancelled"])


class MacroLookupTests(GameTestCase):
    def test_rejects_path_traversal_and_unknown_names(self):
        game = self.make_game()
        with self.assertRaisesRegex(GameError, "invalido"):
            game.run_macro("../secret")
        with self.assertRaisesRegex(GameError, "mini"):
            game.run_macro("nope")

    def test_local_macros_override_shared_ones(self):
        self.write_macro("mini", [{"action": "wait"}, {"action": "wait"}, {"action": "wait"}], sub="local")
        game = self.make_game()
        self.assertEqual(len(game.load_macro_steps("mini")), 3)
        self.assertEqual(game.list_macros(), ["mini"])


def blocking_factory(clicks=1, holder=None):
    """A recorder double that waits until stop() is called (or 5 s pass), then returns ``clicks`` clicks."""

    class _Recorder:
        def __init__(self, backend, title, **kwargs):
            self.release = threading.Event()
            self.started = threading.Event()
            self.kwargs = kwargs
            if holder is not None:
                holder.append(self)

        def record(self):
            self.started.set()
            self.release.wait(5)
            steps = [{"action": "wait_window"}] + [{"action": "click", "x": "50%", "y": "50%"}] * clicks
            return Recording(steps, clicks, 0, 1.0, (400, 800))

        def stop(self):
            self.release.set()

    return _Recorder


class RecordingTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.done = threading.Event()
        self.results = []

    def on_done(self, result):
        self.results.append(result)
        self.done.set()

    def finish(self):
        self.assertTrue(self.done.wait(5), "recording did not finish")
        return self.results[0]

    def test_records_in_the_background_and_saves_to_the_library(self):
        self.backend.input_fn = ScriptedMouse(self.clock.clock, [(1.0, 1.08, 200, 400), (3.0, 3.08, 100, 200)], stop_at=5.0)

        def factory(backend, title, **kwargs):
            return Recorder(backend, title, clock=self.clock.clock, sleep=self.clock.sleep, background_capture=False, **kwargs)

        game = self.make_game(recorder_factory=factory)
        game.start_recording("quest_1", description="Daily", tags=["daily"], on_done=self.on_done)
        result = self.finish()
        self.assertEqual((result.error, result.clicks, result.name), ("", 2, "quest_1"))
        self.assertEqual(result.path, self.macros / "local" / "quest_1.json")
        steps = game.library.load_steps("quest_1")
        self.assertEqual([s["action"] for s in steps], ["wait_window", "click", "wait", "click"])
        status = game.status()
        self.assertEqual((status.busy, status.recording), (False, False))

    def test_only_one_operation_at_a_time_and_stop_saves(self):
        holder = []
        game = self.make_game(recorder_factory=blocking_factory(clicks=2, holder=holder))
        game.start_recording("first", on_done=self.on_done)
        self.assertTrue(holder[0].started.wait(5))
        status = game.status()
        self.assertEqual((status.recording, status.busy), (True, True))
        with self.assertRaises(GameBusy):
            game.run_macro("mini")
        with self.assertRaises(GameBusy):
            game.start_recording("second")
        self.assertTrue(game.stop_recording())
        result = self.finish()
        self.assertEqual(result.clicks, 2)
        self.assertTrue((self.macros / "local" / "first.json").exists())
        self.assertFalse(game.stop_recording())  # nothing left to stop
        game.run_macro("mini")  # and the game is free again

    def test_nothing_recorded_saves_nothing(self):
        holder = []
        game = self.make_game(recorder_factory=blocking_factory(clicks=0, holder=holder))
        game.start_recording("empty", on_done=self.on_done)
        holder[0].started.wait(5)
        game.stop_recording()
        result = self.finish()
        self.assertIn("Nenhum clique", result.error)
        self.assertIsNone(result.path)
        self.assertFalse((self.macros / "local" / "empty.json").exists())

    def test_options_are_forwarded_to_the_recorder(self):
        holder = []
        game = self.make_game(recorder_factory=blocking_factory(holder=holder))
        game.start_recording("opts", anchors=True, stop_vk=0x78, max_seconds=60, on_done=self.on_done)
        holder[0].started.wait(5)
        game.stop_recording()
        self.finish()
        kwargs = holder[0].kwargs
        self.assertEqual((kwargs["anchors"], kwargs["stop_vk"], kwargs["max_seconds"]), (True, 0x78, 60))

    def test_shots_are_saved_and_reported_without_changing_macro_format(self):
        self.backend.size = (20, 20)
        self.backend.input_fn = ScriptedMouse(self.clock.clock, [(1.0, 1.08, 5, 6)], stop_at=2.0, size=(20, 20))

        def factory(backend, title, **kwargs):
            return Recorder(backend, title, clock=self.clock.clock, sleep=self.clock.sleep, background_capture=False, **kwargs)

        game = self.make_game(recorder_factory=factory)
        game.start_recording("visual", shots=True, on_done=self.on_done)
        result = self.finish()
        self.assertEqual(result.error, "")
        self.assertEqual(result.image_count, 2)
        self.assertTrue(result.shots_path.is_file())
        self.assertEqual(result.shots_path.parent.parent, self.macros / "local" / "recordings" / "visual")
        self.assertEqual([s["action"] for s in game.library.load_steps("visual")], ["wait_window", "click"])

    def test_recording_directory_is_unique_and_does_not_create_files(self):
        library = self.make_game().library
        first, second = library.new_recording_dir("visual"), library.new_recording_dir("visual")
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        with self.assertRaises(LibraryError):
            library.new_recording_dir("../evil")

    def test_invalid_requests_are_refused_without_taking_the_game(self):
        game = self.make_game(recorder_factory=blocking_factory())
        for name in ["../evil", "a b"]:
            with self.assertRaises(GameError):
                game.start_recording(name)
        game.library.save("taken", [{"action": "wait"}])
        with self.assertRaisesRegex(GameError, "Ja existe"):
            game.start_recording("taken")
        self.backend.hide_for = 100
        with self.assertRaisesRegex(GameError, "nao encontrada"):
            game.start_recording("fresh")
        self.assertFalse(game.status().busy)

    def test_overwrite_replaces_an_existing_macro(self):
        holder = []
        game = self.make_game(recorder_factory=blocking_factory(clicks=1, holder=holder))
        game.library.save("taken", [{"action": "wait"}])
        game.start_recording("taken", overwrite=True, on_done=self.on_done)
        holder[0].started.wait(5)
        game.stop_recording()
        self.finish()
        self.assertEqual(len(game.library.load_steps("taken")), 2)

    def test_the_input_guard_wraps_the_whole_recording(self):
        events = []

        @contextmanager
        def guard():
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        class Instant:
            def __init__(self, backend, title, **kwargs):
                pass

            def record(self):
                events.append("record")
                return Recording([{"action": "wait_window"}, {"action": "click", "x": 1, "y": 1}], 1, 0, 0.5, (400, 800))

            def stop(self):
                pass

        game = self.make_game(recorder_factory=Instant, input_guard=guard)
        game.start_recording("guarded", on_done=self.on_done)
        self.finish()
        self.assertEqual(events, ["enter", "record", "exit"])

    def test_a_failing_recorder_reports_the_error_and_frees_the_game(self):
        class Broken:
            def __init__(self, backend, title, **kwargs):
                pass

            def record(self):
                raise RecorderError("boom")

            def stop(self):
                pass

        game = self.make_game(recorder_factory=Broken)
        game.start_recording("broken", on_done=self.on_done)
        result = self.finish()
        self.assertEqual((result.error, result.path), ("boom", None))
        self.assertFalse(game.status().busy)


class GuardTests(GameTestCase):
    def setUp(self):
        super().setUp()
        self.settings = replace(self.settings, foreground_input=True)
        self.events = []
        events = self.events

        @contextmanager
        def guard():
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        self.guard = guard
        self.backend.click = lambda hwnd, x, y, foreground: events.append(("click", foreground))
        self.write_macro("two", [{"action": "click", "x": "50%", "y": "50%"}, {"action": "click", "x": "10%", "y": "10%"}])

    def test_foreground_clicks_run_inside_the_guard(self):
        self.make_game(input_guard=self.guard).run_macro("two")
        self.assertEqual(self.events, ["enter", ("click", True), "exit"] * 2)

    def test_background_clicks_need_no_guard(self):
        self.settings = replace(self.settings, foreground_input=False)
        self.make_game(input_guard=self.guard).run_macro("two")
        self.assertEqual(self.events, [("click", False)] * 2)

    def test_without_a_guard_nothing_is_wrapped(self):
        self.make_game().run_macro("two")
        self.assertEqual(self.events, [("click", True)] * 2)


class ScreenshotTests(GameTestCase):
    def test_visible_window_is_captured_without_touching_its_state(self):
        frame = self.make_game().screenshot()
        self.assertEqual((frame.width, frame.height), (400, 800))
        self.assertEqual(self.backend.calls, [("capture",)])

    def test_minimized_window_is_restored_captured_and_minimized_again(self):
        self.backend.minimized = True
        self.make_game().screenshot()
        self.assertEqual(self.backend.calls, [("restore",), ("capture",), ("minimize",)])
        self.assertIn(0.8, self.clock.sleeps)

    def test_minimized_window_during_an_operation_is_refused(self):
        self.backend.minimized = True
        game = self.make_game()
        game._busy.acquire()
        with self.assertRaises(GameBusy):
            game.screenshot()
        self.assertEqual(self.backend.calls, [])

    def test_missing_window(self):
        self.backend.hide_for = 100
        with self.assertRaises(GameError):
            self.make_game().screenshot()


if __name__ == "__main__":
    unittest.main()
