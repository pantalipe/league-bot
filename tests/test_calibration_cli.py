import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from league_bot import __main__ as cli
from league_bot import calibration_cli


class CalibrationCliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {
            "SLAYER_WINDOW_TITLE": "Slayer Legend",
            "TELEGRAM_TOKEN": "",
            "ALLOWED_USER_IDS": "",
        }), mock.patch.object(cli, "_backend", side_effect=AssertionError("offline command created backend")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--env-file", str(Path(tempfile.gettempdir()) / "missing-calibration.env"), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_calibration_help_lists_guided_commands(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["calibrate", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("capture", out.getvalue())
        self.assertIn("guide", out.getvalue())
        self.assertIn("rollback", out.getvalue())

    def test_capture_rejects_count_outside_supported_range_before_game_creation(self):
        code, _, err = self.run_cli("calibrate", "capture", "main", "--count", "1")
        self.assertEqual(code, 1)
        self.assertIn("entre 2 e 60", err)

    def test_diagnose_rejects_unknown_label_without_traceback(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["calibrate", "diagnose", "sample.png", "--state", "unknown"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", err.getvalue())

    def test_offline_validation_failure_is_nonzero_without_backend(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            calibration_cli, "_engine", return_value=SimpleNamespace(
                validate_candidate=lambda session: {"ok": False, "samples": 4, "errors": ["colisao"]}
            )
        ):
            code, out, err = self.run_cli("calibrate", "validate", "--session", tmp)
        self.assertEqual(code, 1)
        self.assertIn("Amostras: 4", out)
        self.assertIn("colisao", err)

    def test_offline_diagnose_prints_anchor_details_without_backend(self):
        frame = SimpleNamespace(width=434, height=810)
        screen = {"name": "main", "anchors": []}
        engine = SimpleNamespace(
            load_image=lambda path: frame,
            catalog=lambda: {"main": screen},
            diagnose=lambda image, profile: {
                "matched": False,
                "size": [434, 810],
                "expected_size": [434, 810],
                "anchors": [{"index": 0, "x": 100, "y": 200, "expected": [1, 2, 3],
                             "actual": [4, 5, 6], "delta": [3, 3, 3], "matched": False}],
            },
        )
        with mock.patch.object(calibration_cli, "_engine", return_value=engine):
            code, out, _ = self.run_cli("calibrate", "diagnose", "sample.png", "--state", "main")
        self.assertEqual(code, 1)
        self.assertIn("434x810; esperado 434x810", out)
        self.assertIn("anchor 0: FALHA pos=(100, 200)", out)
        self.assertIn("esperado=[1, 2, 3] atual=[4, 5, 6] delta=[3, 3, 3]", out)

    def test_offline_diagnose_rejects_unsupported_geometry(self):
        frame = SimpleNamespace(width=400, height=800)
        engine = SimpleNamespace(
            load_image=lambda path: frame,
            catalog=lambda: {"main": {"name": "main", "anchors": []}},
            diagnose=lambda image, profile: {
                "matched": True, "size": [400, 800], "expected_size": [434, 810], "anchors": [],
            },
        )
        with mock.patch.object(calibration_cli, "_engine", return_value=engine):
            code, out, err = self.run_cli("calibrate", "diagnose", "sample.png", "--state", "main")
        self.assertEqual(code, 1)
        self.assertIn("ERRO: tamanho 400x800 nao suportado", err)
        self.assertIn("400x800; esperado 434x810", out)

    def test_apply_does_not_activate_when_validation_fails(self):
        engine = SimpleNamespace(
            validate_candidate=lambda session: {"ok": False, "samples": 2, "errors": ["sem separacao"]},
            apply_candidate=mock.Mock(side_effect=AssertionError("failed candidate applied")),
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(calibration_cli, "_engine", return_value=engine):
            code, _, _ = self.run_cli("calibrate", "apply", "--session", tmp)
        self.assertEqual(code, 1)
        engine.apply_candidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
