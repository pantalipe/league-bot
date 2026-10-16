import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from league_bot import __main__ as cli
from league_bot.config import Settings


class SequenceCliTests(unittest.TestCase):
    def test_battle_check_preflights_real_macros_without_backend(self):
        args = cli.build_parser().parse_args(["sequence", "check", "--battles"])
        with patch.object(cli, "_backend", side_effect=AssertionError("desktop access")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_sequence(Settings(), args), 0)

    def test_buffs_preflight_uses_real_recordings(self):
        from league_bot.slayer.api import open_library
        from league_bot.slayer.macro_sequence import MacroSequence
        from league_bot.slayer.plan import ACTIVATIONS
        prepared = MacroSequence(open_library(Settings()), selected_names=ACTIVATIONS).preflight()
        self.assertEqual(set(prepared), set(ACTIVATIONS))

    def test_check_uses_real_recordings_without_creating_backend(self):
        settings = Settings()
        args = cli.build_parser().parse_args(["sequence", "check"])
        with patch.object(cli, "_backend", side_effect=AssertionError("desktop access")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.cmd_sequence(settings, args), 0)
        self.assertIn("validas", output.getvalue())

    def test_status_does_not_create_backend_or_state(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(data_dir=Path(folder))
            args = cli.build_parser().parse_args(["sequence", "status"])
            with patch.object(cli, "_backend", side_effect=AssertionError("desktop access")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.cmd_sequence(settings, args), 0)
            self.assertIn("Nenhuma", output.getvalue())
            self.assertEqual(list(Path(folder).iterdir()), [])
