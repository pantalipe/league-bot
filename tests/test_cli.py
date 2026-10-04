import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from league_bot import __main__ as cli
from league_bot.recorder import Recording
from tests.fakes import FakeBackend

MISSING_ENV_FILE = Path(tempfile.gettempdir()) / "league_bot-tests-missing.env"
BASE_ENV = {"SLAYER_WINDOW_TITLE": "Slayer Legend", "TELEGRAM_TOKEN": "", "ALLOWED_USER_IDS": ""}


def run_cli(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    environment = dict(BASE_ENV, **(env or {}))
    with mock.patch.dict(os.environ, environment), \
            mock.patch.object(cli, "_backend", lambda: FakeBackend(fill=(230, 230, 230))), \
            mock.patch.object(cli.SlayerGame, "is_running", return_value=False), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--env-file", str(MISSING_ENV_FILE), *argv])
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_pixel_reads_a_color_with_macro_coordinates(self):
        code, out, _ = run_cli("pixel", "50%", "center")
        self.assertEqual(code, 0)
        self.assertIn("400x800", out)
        self.assertIn("[230, 230, 230]", out)

    def test_pixel_outside_the_window_fails(self):
        code, out, _ = run_cli("pixel", "500", "5")
        self.assertEqual(code, 1)
        self.assertIn("fora da janela", out)

    def test_shot_writes_png_or_bmp_by_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            png, bmp = Path(tmp) / "a.png", Path(tmp) / "b.bmp"
            self.assertEqual(run_cli("shot", str(png))[0], 0)
            self.assertEqual(run_cli("shot", str(bmp))[0], 0)
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(bmp.read_bytes()[:2], b"BM")

    def test_windows_lists_sorted_titles(self):
        code, out, _ = run_cli("windows")
        self.assertEqual((code, out.split("\n")[:2]), (0, ["Notepad", "Slayer Legend"]))

    def test_check_passes_with_the_shipped_macro(self):
        code, out, _ = run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("OK    start_game", out)
        self.assertNotIn("TELEGRAM_TOKEN = set", out)

    def test_check_fails_without_a_window_title(self):
        self.assertEqual(run_cli("check", env={"SLAYER_WINDOW_TITLE": ""})[0], 1)

    def test_bad_configuration_exits_with_code_2(self):
        code, _, err = run_cli("status", env={"ALLOWED_USER_IDS": "abc"})
        self.assertEqual(code, 2)
        self.assertIn("Erro de configuracao", err)

    def test_run_without_a_token_explains_what_is_missing(self):
        code, _, err = run_cli("run")
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_TOKEN", err)


RECORDED_STEPS = [{"action": "wait_window"}, {"action": "click", "x": "50%", "y": "50%"}]


class FakeRecorder:
    """Stands in for league_bot.recorder.Recorder so the CLI can be tested without a mouse."""

    result = None
    seen = {}

    def __init__(self, backend, title, **kwargs):
        FakeRecorder.seen = dict(kwargs, title=title)

    def record(self):
        return FakeRecorder.result


class MacroCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        shared = {"description": "Demo", "steps": [{"action": "wait_window"}, {"action": "click", "x": "50%", "y": "50%"}]}
        (self.dir / "shared_demo.json").write_text(json.dumps(shared), encoding="utf-8")
        FakeRecorder.result = Recording(RECORDED_STEPS, clicks=2, skipped_gestures=1, duration=12.4,
                                        window_size=(400, 800), warnings=["something odd"])
        patcher = mock.patch.object(cli, "Recorder", FakeRecorder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cli(self, *argv):
        return run_cli(*argv, env={"SLAYER_MACROS_DIR": str(self.dir)})

    def record(self, *extra, name="mine"):
        return self.cli("record", name, "--delay", "0", *extra)

    def test_macros_lists_shared_and_local(self):
        self.record("-d", "Minha quest", "-t", "daily")
        code, out, _ = self.cli("macros")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"mine\s+local\s+2\s+Minha quest \[daily\]")
        self.assertRegex(out, r"shared_demo\s+shared\s+2\s+Demo")

    def test_show_prints_numbered_steps(self):
        code, out, _ = self.cli("show", "shared_demo")
        self.assertEqual(code, 0)
        self.assertIn("1. wait_window", out)
        self.assertIn("2. click x=50% y=50%", out)

    def test_record_saves_a_local_macro_with_metadata(self):
        code, out, _ = self.record("-d", "Minha quest", "-t", "daily", "-t", "easy")
        self.assertEqual(code, 0)
        document = json.loads((self.dir / "local" / "mine.json").read_text(encoding="utf-8"))
        self.assertEqual((document["description"], document["tags"]), ("Minha quest", ["daily", "easy"]))
        self.assertEqual(document["window"], {"width": 400, "height": 800})
        self.assertEqual(document["steps"], RECORDED_STEPS)
        self.assertIn("Macro 'mine' salva: 2 clique(s)", out)
        self.assertIn("aviso: something odd", out)
        self.assertIn("1 gesto(s)", out)
        self.assertEqual(FakeRecorder.seen["title"], "Slayer Legend")

    def test_record_options_reach_the_recorder(self):
        self.record("--no-anchor", "--stop-key", "f9", "--max-seconds", "60")
        self.assertEqual((FakeRecorder.seen["anchors"], FakeRecorder.seen["stop_vk"], FakeRecorder.seen["max_seconds"]),
                         (False, 0x78, 60.0))

    def test_nothing_recorded_saves_nothing(self):
        FakeRecorder.result = Recording([{"action": "wait_window"}], 0, 0, 3.0, (400, 800))
        code, out, _ = self.record()
        self.assertEqual(code, 1)
        self.assertIn("nada foi salvo", out)
        self.assertFalse((self.dir / "local").exists())

    def test_record_refuses_existing_names_unless_forced(self):
        self.assertEqual(self.record()[0], 0)
        code, _, err = self.record()
        self.assertEqual(code, 1)
        self.assertIn("Ja existe", err)
        self.assertEqual(self.record("--force")[0], 0)
        self.assertEqual(self.record(name="shared_demo")[0], 1)

    def test_bad_name_and_bad_stop_key_are_reported(self):
        self.assertEqual(self.record(name="../evil")[0], 1)
        code, _, err = self.record("--stop-key", "escape")
        self.assertEqual(code, 1)
        self.assertIn("F1-F12", err)

    def test_rename_and_delete_only_work_on_local_macros(self):
        self.record()
        self.assertEqual(self.cli("rename", "mine", "renamed")[0], 0)
        self.assertTrue((self.dir / "local" / "renamed.json").exists())
        self.assertEqual(self.cli("delete", "renamed")[0], 0)
        code, _, err = self.cli("delete", "shared_demo")
        self.assertEqual(code, 1)
        self.assertIn("compartilhada", err)


if __name__ == "__main__":
    unittest.main()
