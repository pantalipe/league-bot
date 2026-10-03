import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from slayerbot.config import Settings
from slayerbot.game import GameBusy, GameError, SlayerGame
from slayerbot.macro import MacroError, MacroRunner
from tests.fakes import FakeBackend, FakeTime


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
