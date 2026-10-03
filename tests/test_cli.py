import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from league_bot import __main__ as cli
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


if __name__ == "__main__":
    unittest.main()
